git pull 
cd autoppia_iwa_module && git pull origin main && cd ..
git submodule update --init --recursive
scripts/mongo/deploy_docker_mongo.sh
pip install -e autoppia_iwa_module
