git pull 
cd autoppia_iwa && git pull origin main && cd ..
git submodule update --init --recursive
scripts/mongo/deploy_docker_mongo.sh