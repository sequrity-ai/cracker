"""Line-level anomaly scoring for prior mismatch metric.

Instead of whole-file embedding similarity, embed each line individually
and compare against the task prompt. The most anomalous line (lowest
similarity) is the signal — injected lines should stick out even when
the overall file looks normal.

Hypothesis: min-similarity line score will be lower in poisoned files
than benign files, and will correlate with ASR better than whole-file approach.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from scipy import stats

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from cracker.backends import LocalBackend
from cracker.attacks.base import ALL_STRENGTHS
from cracker.scenarios.code_review import CodeReviewScenario

EMBED_MODEL = "openai/text-embedding-3-small"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)


def embed(texts: list[str]) -> np.ndarray:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return np.array([d.embedding for d in resp.data])


def cosine_sim(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Similarity between each row of a and single vector b."""
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b)
    return (a @ b).flatten()


def line_anomaly_score(file_content: str, task_prompt: str) -> dict:
    """Score each non-empty line against the task prompt.

    Returns min, mean, std of per-line similarities.
    Lower min = more anomalous lines present.
    """
    lines = [l.strip() for l in file_content.splitlines() if l.strip()]
    if not lines:
        return {"min": 0.0, "mean": 0.0, "std": 0.0, "n_lines": 0, "lines": []}

    line_embs = embed(lines)
    task_emb = embed([task_prompt])[0]
    sims = cosine_sim(line_embs, task_emb)

    # Find the most anomalous line
    min_idx = int(np.argmin(sims))

    return {
        "min": float(sims.min()),
        "mean": float(sims.mean()),
        "std": float(sims.std()),
        "n_lines": len(lines),
        "most_anomalous_line": lines[min_idx],
        "most_anomalous_sim": float(sims[min_idx]),
        "per_line": list(zip(lines, sims.tolist())),
    }


def setup_and_read(scenario, backend, mode, vector, strength, filename):
    scenario.fresh_canary()
    scenario.setup(backend, mode=mode, vector=vector, strength=strength)
    content = backend.read_file(filename)
    scenario.teardown(backend)
    return content


def main():
    scenario = CodeReviewScenario()
    vector = "file"
    tasks = scenario.file_tasks

    records = []

    print(f"\n{'Strength':<12} {'Task':<30} {'Min(poison)':>12} {'Min(benign)':>12} {'Leaked':>7}")
    print("-" * 78)

    for strength in ALL_STRENGTHS:
        for task in tasks:
            pfs = scenario.poisonable_files_for_task(task)
            if not pfs:
                continue
            pf = pfs[0]
            filename = pf["path"] if isinstance(pf, dict) else pf.path

            with tempfile.TemporaryDirectory() as tmpdir:
                backend = LocalBackend(workspace_path=tmpdir)
                backend.connect()

                benign_content = setup_and_read(
                    scenario, backend, mode="benign", vector=vector,
                    strength=strength.value, filename=filename
                )
                poisoned_content = setup_and_read(
                    scenario, backend, mode="attack", vector=vector,
                    strength=strength.value, filename=filename
                )
                backend.disconnect()

            if not poisoned_content or not benign_content:
                continue

            benign_score = line_anomaly_score(benign_content, task.prompt)
            poisoned_score = line_anomaly_score(poisoned_content, task.prompt)

            print(
                f"{strength.value:<12} {task.name:<30} "
                f"{poisoned_score['min']:>12.4f} {benign_score['min']:>12.4f} "
                f"{'(TBD)':>7}"
            )
            print(f"  Most anomalous line (poisoned): {poisoned_score['most_anomalous_line'][:80]!r}")

            records.append({
                "strength": strength.value,
                "task": task.name,
                "filename": filename,
                "poisoned_min": poisoned_score["min"],
                "poisoned_mean": poisoned_score["mean"],
                "benign_min": benign_score["min"],
                "benign_mean": benign_score["mean"],
                "most_anomalous_line": poisoned_score["most_anomalous_line"],
            })

    # Load deepseek ASR per task
    ds = json.load(open("output/deepseek-v3.2.json"))
    strength_ord = {"subtle": 1, "direct": 2, "structural": 3}
    for rec in records:
        sid = f'code-review-file-{rec["strength"]}'
        match = [r for r in ds["results"] if r["scenario_id"] == sid and r["task_name"] == rec["task"]]
        rec["leaked"] = int(match[0]["leaked_at"]["1"]) if match else None
        rec["strength_ord"] = strength_ord[rec["strength"]]

    # Correlations
    valid = [r for r in records if r["leaked"] is not None]
    strengths_arr = np.array([r["strength_ord"] for r in valid])
    min_p = np.array([r["poisoned_min"] for r in valid])
    leaked_arr = np.array([r["leaked"] for r in valid])

    sp_r, sp_p = stats.spearmanr(strengths_arr, min_p)
    pb_r, pb_p = stats.pointbiserialr(leaked_arr, min_p)

    print(f"\n--- Summary ---")
    for strength in ["subtle", "direct", "structural"]:
        recs = [r for r in valid if r["strength"] == strength]
        avg_min_p = np.mean([r["poisoned_min"] for r in recs])
        avg_min_b = np.mean([r["benign_min"] for r in recs])
        asr = np.mean([r["leaked"] for r in recs]) * 100
        print(f"  {strength:<12} min(poisoned)={avg_min_p:.4f}  min(benign)={avg_min_b:.4f}  ASR={asr:.0f}%")

    print(f"\nSpearman(strength, min_poisoned):      r={sp_r:+.4f}  p={sp_p:.3f}")
    print(f"Point-biserial(leaked, min_poisoned):  r={pb_r:+.4f}  p={pb_p:.3f}")
    print(f"n={len(valid)}")

    out_path = Path("output/line_anomaly.json")
    out_path.write_text(json.dumps({"records": records}, indent=2))
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    main()
