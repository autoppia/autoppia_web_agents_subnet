# IWA Reinforcement Learning Environment

This document summarizes the environment that lives under the [`rl/`](/rl) package. The goal is to keep the design of the OpenAI Gym compatible environment explicit and decouple it from any particular training recipe.

## High-level design

* **Environment class**: [`IWAWebEnv`](../rl/envs/iwa_gym_env.py) implements the Gymnasium API (`reset`, `step`). It only depends on the lightweight [`Browser`](/rl/drivers/browser.py) facade and the [`IWAValidator`](/rl/validator/iwa_evaluator_client.py) adapter.
* **Executor separation**: the environment expects a `BrowserAdapter` that wraps the actual Playwright/IWA executor. Production miners can inject the adapter that already exists in `autoppia_iwa`, while unit tests can supply mocks. [`ConcurrentExecutorAdapter`](../rl/drivers/concurrent_adapter.py) resolves the concurrent Playwright executor exposed by `AppBootstrap` and converts its snapshots to the normalized `BrowserSnapshot` structure.
* **Task sourcing**: `IWAValidator.sample_task` is responsible for returning [`TaskSpec`](../rl/envs/types.py). For local experiments you can configure a static `task_pool` inside [`rl/configs/env.yaml`](../rl/configs/env.yaml). When the `autoppia_iwa` stack is available, [`ConcurrentEvaluatorAdapter`](../rl/validator/concurrent_adapter.py) can be referenced from the same config file to reuse the production task repository and concurrent evaluator.

## Action space

The discrete action space is structured as follows (`topk` defaults to 24):

| Segment | Description |
| ------- | ----------- |
| `0` | `NOOP` |
| `1 .. K` | `CLICK_i` – Click the `i`-th ranked DOM element |
| `K+1 .. 2K` | `FOCUS_i` – Focus the `i`-th ranked DOM element |
| `2K+0` | `TYPE_CONFIRM` – Type contextual text and press Enter |
| `2K+1` | `SUBMIT` – Trigger form submission |
| `2K+2` | `SCROLL_UP` |
| `2K+3` | `SCROLL_DOWN` |
| `2K+4` | `BACK` |

The [`Browser`](../rl/drivers/browser.py) exposes capability flags (`can_submit`, `has_focusable_inputs`, `can_scroll`, `can_go_back`), which the environment uses to build an action mask that disables invalid macros. Element level validity is handled by the Top‑K ranker.

## DOM ranking

[`rank_clickables`](../rl/envs/dom_ranker.py) sorts the elements emitted by the browser snapshot. The heuristic uses:

* Visibility / enabled state
* Role and tag priors (buttons, links, inputs)
* Similarity between element labels and the task goal
* Whether the element is in the viewport
* Text length as a proxy for information density

The function returns both ranked elements and boolean masks indicating whether each entry is safe to click or focus.

## Observation structure

[`ObservationBuilder`](../rl/envs/obs_builders.py) converts the task and browser snapshot into tensors:

* `goal_ids` – hashed tokens (length 64)
* `dom_ids` – hashed tokens from the visible DOM (length 256)
* `url_id` – hashed identifier of the current URL
* `prev_actions` – last 10 discrete actions
* `topk_meta` – six scalar features per ranked element (role id, clickable, focusable, editable, viewport flag, normalized text length)
* `topk_text_ids` – hashed tokens of each ranked element’s text (length 12 per element)
* `inputs_filled_ratio` – fraction of non-empty form fields
* `cart_items` – numeric cart count from the snapshot

All shapes and vocab sizes are configurable via the `observations` section in [`env.yaml`](../rl/configs/env.yaml).

## Reward shaping

[`RewardComputer`](../rl/envs/rewards.py) combines dense shaping with the external evaluator:

* `+1.0` on success (`validator.evaluate` reports `success=True`)
* `+0.1` for milestones (URL change, form field filled, cart increase)
* Optional shaped reward / milestones forwarded by the validator client
* `−0.001` per step (time cost)
* `−0.05` for invalid actions and loop penalties

Loop detection is handled inside the environment by tracking repeated signatures over a sliding window (default: 6 steps with a threshold of 3 repeats).

## Configuration entry point

The defaults live in [`rl/configs/env.yaml`](../rl/configs/env.yaml). Override values by passing a dictionary to the environment constructor or by loading the YAML file and passing it as `cfg`.

```python
from pathlib import Path
import yaml
from rl import IWAWebEnv

cfg = yaml.safe_load(Path("rl/configs/env.yaml").read_text())
env = IWAWebEnv(cfg)
obs, info = env.reset()
```

This documentation focuses purely on the environment layer. Training scripts (PPO, BC, etc.) can be added later without modifying the environment contract.
