# Subnet 36 (IWA) — How It Works

This document explains the subnet flow in a clear, compact way.

## 🌍 **IWA (Infinite Web Arena)** at a Glance

IWA (Infinite Web Arena) is the evaluation engine. It generates web tasks, runs real browser actions, and checks success with objective tests.

## 👥 Roles

- **Miner**: announces **metadata** (name, image, GitHub URL). The validator will clone and deploy the GitHub URL inside a sandbox.
- **Validator**: generates **tasks**, deploys agents in the sandbox, evaluates them, publishes **scores/weights**, and sends data to **IWAP**.
- **IWAP**: backend that stores **rounds, tasks, evaluations, and artifacts**. `https://infinitewebarena.autoppia.com/home`

## 📆 Seasons, Rounds, and Tasks

- **Season**: a fixed window of epochs. At the start of each season, the validator generates **N tasks**.
- **Round**: repeated evaluation windows inside the season. A season lasts **Y epochs** and each round lasts **X epochs**, so each season has **M = Y / X** rounds (an exact integer).
- **Task reuse**: the **same N tasks** are used in **every round** of the season. Tasks only change when a new season starts.
- **Handshake timing**: at the start of each round, miners answer the handshake with their metadata.

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

`https://infinitewebarena.autoppia.com/home`
