from autoppia_web_agents_subnet.validator.season_manager import SeasonManager

sm = SeasonManager()
sm.task_generated_season = 1

# Test with block 4600
season_num = sm.get_season_number(4600)
print(f"Block 4600 -> Season {season_num}")
print(f"task_generated_season: {sm.task_generated_season}")
print(f"should_start_new_season: {sm.should_start_new_season(4600)}")
