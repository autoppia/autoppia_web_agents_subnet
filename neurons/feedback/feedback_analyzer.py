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
    
    # We'll gather:
    #   - final_score in a global list
    #   - reward_score/time_factor grouped by (validator_id, miner_id)
    final_scores = []
    reward_scores_map = defaultdict(list)
    time_factor_map = defaultdict(list)
    
    for item in data:
        # Grab relevant fields
        eval_result = item.get("evaluation_result", {})
        
        final_score = eval_result.get("final_score", None)
        if final_score is not None:
            final_scores.append(final_score)
        
        reward_score = eval_result.get("reward_score", None)
        time_factor = eval_result.get("time_factor", None)
        
        validator_id = str(item.get("validator_id", "unknown_validator"))
        miner_id = str(item.get("miner_id", "unknown_miner"))
        
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
    # 3) We need a combined set of all validator_id and miner_id from both maps
    # -------------------------------------------------------------------------
    all_validator_ids = set()
    all_miner_ids = set()

    # Gather from reward_scores_map
    for (val_id, min_id) in reward_scores_map.keys():
        all_validator_ids.add(val_id)
        all_miner_ids.add(min_id)
    # Gather from time_factor_map
    for (val_id, min_id) in time_factor_map.keys():
        all_validator_ids.add(val_id)
        all_miner_ids.add(min_id)
    
    # Now sort them exactly once
    validators = sorted(all_validator_ids)
    miners = sorted(all_miner_ids)
    
    # -------------------------------------------------------------------------
    # 4) TABLE of average "reward_score"
    # -------------------------------------------------------------------------
    print("\n=== Average reward_score by Validator (rows) and Miner (columns) ===")
    matrix_reward = []
    for v in validators:
        row = []
        for m in miners:
            scores = reward_scores_map.get((v, m), [])
            if scores:
                row.append(round(statistics.mean(scores), 2))
            else:
                row.append(None)
        matrix_reward.append(row)
    
    # Print table
    if tabulate:
        header = ["Validator \\ Miner"] + miners
        table = []
        for i, v in enumerate(validators):
            table.append([v] + matrix_reward[i])
        print(tabulate(table, headers=header, tablefmt="pretty"))
    else:
        # Basic fallback printing
        print("    " + "   ".join([f"{m:>10}" for m in miners]))
        for i, v in enumerate(validators):
            row_str = [(f"{x:.2f}" if x is not None else "N/A").rjust(10) for x in matrix_reward[i]]
            print(f"{v:>3} " + " ".join(row_str))
    
    # -------------------------------------------------------------------------
    # 5) TABLE of average "time_factor"
    # -------------------------------------------------------------------------
    print("\n=== Average time_factor by Validator (rows) and Miner (columns) ===")
    matrix_time_factor = []
    for v in validators:
        row = []
        for m in miners:
            times = time_factor_map.get((v, m), [])
            if times:
                row.append(round(statistics.mean(times), 2))
            else:
                row.append(None)
        matrix_time_factor.append(row)
    
    if tabulate:
        header = ["Validator \\ Miner"] + miners
        table = []
        for i, v in enumerate(validators):
            table.append([v] + matrix_time_factor[i])
        print(tabulate(table, headers=header, tablefmt="pretty"))
    else:
        print("    " + "   ".join([f"{m:>10}" for m in miners]))
        for i, v in enumerate(validators):
            row_str = [(f"{x:.2f}" if x is not None else "N/A").rjust(10) for x in matrix_time_factor[i]]
            print(f"{v:>3} " + " ".join(row_str))


if __name__ == "__main__":
    path_to_your_json = "feedback_tasks.json"
    main(path_to_your_json)
