import json
import statistics
from collections import defaultdict

# Optional: for nicely formatted text tables (pip install tabulate)
try:
    from tabulate import tabulate
except ImportError:
    tabulate = None

def main(json_file_path: str):
    # 1) Load data from JSON file
    with open(json_file_path, "r") as f:
        data = json.load(f)
    
    # If your file is a single large list of dictionaries, then data is that list.
    # E.g.:
    # data = [
    #   {
    #       "version": "...",
    #       "validator_id": "...",
    #       "miner_id": "...",
    #       ...
    #   },
    #   ...
    # ]
    
    # We’ll gather stats for final_score, reward_score, and time_factor.
    final_scores = []
    
    # We’ll also gather reward_score/time_factor in a grouped manner:
    # Key = (validator_id, miner_id) => values = list of reward_scores or time_factors
    reward_scores_map = defaultdict(list)
    time_factor_map = defaultdict(list)
    
    for item in data:
        # 1. Grab final_score
        #    The object has "evaluation_result" with "final_score"
        #    If missing, default to None (skip)
        eval_result = item.get("evaluation_result", {})
        
        final_score = eval_result.get("final_score", None)
        if final_score is not None:
            final_scores.append(final_score)
        
        # 2. Grab reward_score
        reward_score = eval_result.get("reward_score", None)
        
        # 3. Grab time_factor
        time_factor = eval_result.get("time_factor", None)
        
        # We also need validator_id and miner_id from top-level fields
        validator_id = str(item.get("validator_id", "unknown_validator"))
        miner_id = str(item.get("miner_id", "unknown_miner"))
        
        # Group them by (validator_id, miner_id)
        # Only add if reward_score/time_factor is not None
        if reward_score is not None:
            reward_scores_map[(validator_id, miner_id)].append(reward_score)
        if time_factor is not None:
            time_factor_map[(validator_id, miner_id)].append(time_factor)
    
    # -------------------------------------------------------------------------
    # 2) GLOBAL OVERVIEW of "final_score"
    # -------------------------------------------------------------------------
    print("\n=== Global Overview of final_score ===")
    if len(final_scores) == 0:
        print("No final_score data found.")
    else:
        count_fs = len(final_scores)
        avg_fs = statistics.mean(final_scores)
        min_fs = min(final_scores)
        max_fs = max(final_scores)
        print(f"Count of final_score: {count_fs}")
        print(f"Average final_score: {avg_fs:.2f}")
        print(f"Min final_score    : {min_fs:.2f}")
        print(f"Max final_score    : {max_fs:.2f}")
    
    # -------------------------------------------------------------------------
    # 3) TABLE of average "reward_score" by (validator_id, miner_id)
    # -------------------------------------------------------------------------
    print("\n=== Average reward_score by Validator (rows) and Miner (columns) ===")
    # Collect all unique validator_ids and miner_ids to build a pivot table
    validators = set()
    miners = set()
    for (val_id, min_id) in reward_scores_map.keys():
        validators.add(val_id)
        miners.add(min_id)
    
    # Sort them so the table is consistent
    validators = sorted(validators)
    miners = sorted(miners)
    
    # Build a 2D matrix: rows = validators, columns = miners
    matrix_reward = []
    for v in validators:
        row = []
        for m in miners:
            scores = reward_scores_map.get((v, m), [])
            if len(scores) == 0:
                row.append(None)  # or "N/A"
            else:
                row.append(round(statistics.mean(scores), 2))
        matrix_reward.append(row)
    
    # Print using tabulate if available, otherwise do your own printing
    if tabulate:
        header = ["Validator \\ Miner"] + miners
        table = []
        for i, v in enumerate(validators):
            table.append([v] + matrix_reward[i])
        
        print(tabulate(table, headers=header, tablefmt="pretty"))
    else:
        # Basic printing if tabulate is not installed
        print("    " + "    ".join([f"{m:>10}" for m in miners]))
        for i, v in enumerate(validators):
            row_str = [f"{x if x is not None else 'N/A':>10}" for x in matrix_reward[i]]
            print(f"{v:>3} " + " ".join(row_str))
    
    # -------------------------------------------------------------------------
    # 4) TABLE of average "time_factor" by (validator_id, miner_id)
    # -------------------------------------------------------------------------
    print("\n=== Average time_factor by Validator (rows) and Miner (columns) ===")
    
    # We can reuse the sets of validators/miners, but let's ensure we include
    # any new ones that only appear in time_factor_map
    for (val_id, min_id) in time_factor_map.keys():
        validators.add(val_id)
        miners.add(min_id)
    
    validators = sorted(validators)
    miners = sorted(miners)
    
    matrix_time_factor = []
    for v in validators:
        row = []
        for m in miners:
            times = time_factor_map.get((v, m), [])
            if len(times) == 0:
                row.append(None)
            else:
                row.append(round(statistics.mean(times), 2))
        matrix_time_factor.append(row)
    
    if tabulate:
        header = ["Validator \\ Miner"] + miners
        table = []
        for i, v in enumerate(validators):
            table.append([v] + matrix_time_factor[i])
        
        print(tabulate(table, headers=header, tablefmt="pretty"))
    else:
        print("    " + "    ".join([f"{m:>10}" for m in miners]))
        for i, v in enumerate(validators):
            row_str = [f"{x if x is not None else 'N/A':>10}" for x in matrix_time_factor[i]]
            print(f"{v:>3} " + " ".join(row_str))


if __name__ == "__main__":
    # Example usage:
    # python analyze_feedback.py
    # (Update the path to your JSON file that has the list of TaskFeedbackSynapse data)
    path_to_your_json = "feedback_tasks.json"  # or feedback_tasks.json, etc.
    main(path_to_your_json)
