docker run -it --rm --net=host --ipc=host --gpus all --privileged \
	-v /home/${USER}/STAP:/home/${USER}/STAP \
	-e DISPLAY=unix$DISPLAY \
	-e NVIDIA_VISIBLE_DEVICES=all \
	-e NVIDIA_DRIVER_CAPABILITIES=all \
	--name ${USER}_stap_docker stap_docker bash
