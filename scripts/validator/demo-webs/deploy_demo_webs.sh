CURRENT_DIR=$(pwd)
WEBS_DEMO_PATH="${WEBS_DEMO_PATH:-../autoppia_webs_demo}"

if [ ! -d "$WEBS_DEMO_PATH/scripts" ]; then
  echo "webs_demo path not found at ${WEBS_DEMO_PATH}. Set WEBS_DEMO_PATH to the webs_demo repository path." >&2
  exit 1
fi

cd "$WEBS_DEMO_PATH/scripts"
chmod +x install_docker.sh
./install_docker.sh
chmod +x setup.sh
./setup.sh -y
cd "$CURRENT_DIR"
