git pull 
cd autoppia_iwa_module && git pull origin main && pip install -e autoppia_iwa_module && cd ..
git submodule update --init --recursive
scripts/mongo/deploy_docker_mongo.sh
pip install -e .
