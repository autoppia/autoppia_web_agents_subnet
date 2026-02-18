# Subnet 36 (IWA) — How It Works

This document explains the subnet flow in a clear, compact way.

## 🌍 IWA at a Glance

IWA (Infinite Web Arena) is the evaluation engine. It generates web tasks, runs real browser actions, and checks success with objective tests.

## 👥 Roles

- **Validator**: generates tasks, evaluates agents, publishes scores/weights.
- **Miner**: announces metadata (name, image, GitHub URL).
- **IWAP**: backend that stores rounds, tasks, evaluations, and artifacts.

## 📆 Seasons and Rounds

- Time is divided into **seasons**, each lasting a fixed number of epochs.
- Each season contains multiple **rounds**.
- At the start of each round, miners answer the handshake with their metadata.

## ✅ Tasks per Season

- At the beginning of a season, the validator generates **N tasks**.
- Those **same N tasks** are reused across **all rounds** in that season.
- Tasks change only when the **season changes**.

## 🤝 Handshake (Start of Round)

Miners respond with:

- `MINER_AGENT_NAME`
- `MINER_AGENT_IMAGE`
- `MINER_GITHUB_URL`

The miner itself does not execute tasks. The validator will clone and run the repo.

## 🧪 Evaluation Flow

For each miner selected in a round:

1. Clone the miner repo from the GitHub URL.
2. Run it inside a sandbox container.
3. Call the agent’s **POST `/act`** endpoint step‑by‑step.
4. Execute the returned actions in a browser.
5. Validate outcomes with IWA tests.
6. Compute and store scores.

## 🔁 Re‑evaluation Rules

- If the repo **commit is unchanged** during the same season, it is **not re‑evaluated**.
- To be evaluated again in the same season, submit a **new commit URL**.
- When a **new season** starts, miners are evaluated again even if the commit is unchanged.

## 🏆 End of Season

- Scores across the season determine the **season winner**.
- The validator publishes final weights based on round results.

## 📊 Dashboard

Track subnet status here:

`infinitewebarena.autoppia.com`
