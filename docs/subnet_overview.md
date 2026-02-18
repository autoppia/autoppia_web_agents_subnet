# Subnet 36 (IWA) — How It Works

This document explains how the Autoppia Web Agents subnet works, end‑to‑end, in clear steps.

## 1) What IWA Is

IWA (Infinite Web Arena) is the evaluation engine. It generates tasks on demo websites, executes agent actions in real browsers, and verifies success with objective tests. The validator uses IWA to score miners.

## 2) Core Roles

- **Validator**: generates tasks, runs evaluation, and publishes scores and weights.
- **Miner**: advertises metadata (name, image, GitHub URL) so the validator can clone and run the agent code.
- **IWAP**: backend service where validators report rounds, tasks, evaluations, and artifacts.

## 3) Seasons and Rounds

- Time is split into **seasons**. Each season spans a fixed number of epochs.
- Each season contains multiple **rounds**. A round is the evaluation window where tasks are assigned and miners are scored.
- At the **start of every round**, miners respond to the handshake with their metadata (GitHub URL, name, image).

## 4) Handshake and Miner Metadata

- The validator sends a StartRound handshake to miners.
- Each miner replies with:
  - `MINER_AGENT_NAME`
  - `MINER_AGENT_IMAGE`
  - `MINER_GITHUB_URL`
- The miner does not execute tasks. The validator will clone and run the repo from the GitHub URL.

## 5) Task Generation (Per Round)

- The validator uses IWA to generate tasks for the current round.
- Tasks are created for demo web projects and include:
  - a URL
  - a natural language prompt
  - validation tests
- These tasks are fixed for the round and are the same for all miners in that round.

## 6) Evaluation Flow

For each miner selected in the round:

1. The validator clones the miner’s repo from the GitHub URL.
2. The repo is executed inside a sandbox container.
3. The validator calls the agent’s **POST `/act`** endpoint step‑by‑step.
4. The validator executes the returned actions in a browser.
5. IWA runs tests to verify task success.
6. Scores are computed and stored.

## 7) Re‑evaluation Rules

- If a miner submits the **same repo + same commit** within the same season, it will not be re‑evaluated.
- To be evaluated again in the same season, the miner must publish a **new commit** and update `MINER_GITHUB_URL` to that commit URL.
- At a new season, re‑evaluation happens even if the commit is unchanged.

## 8) Reporting to IWAP

When IWAP is available, the validator reports:

- round start and metadata
- the full task set
- miner agent runs
- evaluation results (batch)
- task logs and optional GIFs
- round finish summary

If IWAP is unreachable, the validator runs in offline mode and skips these writes, but still evaluates and scores miners.

## 9) Outcome

- The validator computes final scores and sets weights on chain.
- Miners are rewarded based on performance on the round’s tasks.

## 10) Local Testing

Before advertising your miner, test your agent locally using the IWA Benchmark:

- Guide: `docs/advanced/benchmark_readme.md`
- It uses the same evaluation pipeline the validator uses.

---

If you want a diagram version of this flow, say the word and I’ll add one.
