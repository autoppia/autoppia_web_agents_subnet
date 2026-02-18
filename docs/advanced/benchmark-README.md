# 🔬 Benchmark Guide (IWA)

This benchmark lives in the `autoppia_iwa` repo. Use it to validate your agent locally before announcing your miner.

## Quick Start

1. **Clone repos as siblings** (if you haven't):

```bash
git clone https://github.com/autoppia/autoppia_web_agents_subnet
git clone https://github.com/autoppia/autoppia_iwa.git
git clone https://github.com/autoppia/autoppia_webs_demo.git
```

2. **Deploy demo webs** (required for evaluation):

```bash
WEBS_DEMO_PATH=${WEBS_DEMO_PATH:-../autoppia_webs_demo}
chmod +x "$WEBS_DEMO_PATH/scripts/setup.sh"
"$WEBS_DEMO_PATH/scripts/setup.sh"
```

3. **Run the benchmark**:

```bash
cd ../autoppia_iwa
python -m autoppia_iwa.entrypoints.benchmark.run
```

## Important Notes

- Your agent must expose **POST `/act`** (this is what the benchmark and validator call).
- The benchmark configuration lives in `autoppia_iwa/entrypoints/benchmark/run.py`.
- Full reference: `autoppia_iwa/entrypoints/benchmark/README.md`.
