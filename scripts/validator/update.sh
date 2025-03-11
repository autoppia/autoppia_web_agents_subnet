git pull 
cd autoppia_iwa_module && git pull origin main && pip install -e . && cd ..
git submodule update --init --recursive
scripts/mongo/deploy_mongo_docker.sh -y
pip install -e .
