export IMAGE_NAME=document-reader
docker-compose -f document-reader.yml -p document-reader down --remove-orphans
docker rmi -f document-reader
gunzip -c document-reader.tgz | docker load
docker-compose -f document-reader.yml -p document-reader up -d --remove-orphans