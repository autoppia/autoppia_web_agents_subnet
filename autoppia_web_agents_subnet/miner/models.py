from typing import Optional


class MinerStats:
    """
    A simple class for tracking aggregate statistics across multiple tasks:
      - number of tasks
      - average reward
      - average execution time
    """

    def __init__(self):
        self.num_tasks: int = 0
        self.total_reward: float = 0.0
        self.total_execution_time: float = 0.0

    def log_feedback(self, reward: Optional[float], execution_time: Optional[float]):
        """
        Logs feedback by incrementing number of tasks and updating total
        reward and total execution time.
        """
        if reward is None:
            reward = 0.0
        if execution_time is None:
            execution_time = 0.0

        self.num_tasks += 1
        self.total_reward += reward
        self.total_execution_time += execution_time

    @property
    def avg_reward(self) -> float:
        if self.num_tasks == 0:
            return 0.0
        return self.total_reward / self.num_tasks
    
    @property
    def avg_score(self) -> float:
        """Backward compatibility alias for avg_reward."""
        return self.avg_reward

    @property
    def avg_execution_time(self) -> float:
        if self.num_tasks == 0:
            return 0.0
        return self.total_execution_time / self.num_tasks
