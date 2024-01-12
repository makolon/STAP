FROM nvidia/cuda:11.3.1-devel-ubuntu20.04

ENV DEBIAN_FRONTEND=noninteractive

# Set up user
ARG USER
WORKDIR /home/$USER/STAP

# Set default shell to /bin/bash
SHELL ["/bin/bash", "-c"]

# Install system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    cmake \
    curl \
    ffmpeg \
    freeglut3-dev \
    gcc \
    git \
    ibverbs-providers \
    libffi-dev \
    libglfw3 \
    libglfw3-dev \
    libgl1-mesa-glx \
    libgl1-mesa-dev \
    libgles2-mesa-dev \
    libglew-dev \
    libglu1-mesa-dev \
    libibverbs1 \
    libjpeg-dev \
    libosmesa6-dev \
    libpng-dev \
    librdmacm1 \
    libssl-dev \
    libvulkan1 \
    libx11-6 \
    llvm-9-dev \
    openjdk-8-jdk \
    openssh-client \
    patchelf \
    python-pygame \
    python3-dev \
    python3-pip \
    swig \
    unzip \
    vim \
    vulkan-utils \
    wget \
    x11-xserver-utils \
    xvfb \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Install python packages
RUN pip install --upgrade pip
RUN pip install \
    absl-py==1.4.0 \
    async-timeout==4.0.2 \
    atomicwrites==1.4.1 \
    axial_attention==0.6.1 \
    beautifulsoup4==4.12.2 \
    black==23.12.1 \
    cachetools==5.3.1 \
    certifi==2023.5.7 \
    charset-normalizer==3.1.0 \
    cloudpickle==2.2.1 \
    contourpy==1.1.0 \
    ctrlutils==1.4.1 \
    cycler==0.11.0 \
    docstring-parser==0.14.1 \
    easydict==1.11 \
    einops==0.7.0 \
    fairscale==0.4.13 \
    filelock==3.12.2 \
    flake8==7.0.0 \
    fonttools==4.40.0 \
    frozendict==2.3.8 \
    functorch==0.2.1 \
    gdown==4.7.1 \
    google-auth==2.20.0 \
    google-auth-oauthlib==1.0.0 \
    grpcio==1.56.0 \
    gym==0.26.2 \
    gym-notices==0.0.8 \
    h5py==3.10.0 \
    idna==3.4 \
    imageio==2.33.1 \
    importlib-metadata==6.7.0 \
    importlib-resources==5.12.0 \
    ipdb==0.13.13 \
    kiwisolver==1.4.4 \
    kornia==0.6.5 \
    lazy-loader==0.2 \
    markdown==3.4.3 \
    markdown-it-py==3.0.0 \
    markupsafe==2.1.3 \
    matplotlib==3.7.4 \
    mdurl==0.1.2 \
    moviepy==1.0.3 \
    mypy==1.8.0 \
    networkx==3.1 \
    numpy==1.24.3 \
    oauthlib==3.2.2 \
    opencv-python==4.8.1.78 \
    packaging==23.2 \
    pandas==2.0.2 \
    pexpect==4.8.0 \
    Pillow==9.5.0 \
    protobuf==4.23.3 \
    ptyprocess==0.7.0 \
    pyasn1==0.5.0 \
    pyasn1-modules==0.3.0 \
    pybullet==3.2.5 \
    pygments==2.15.1 \
    pyglet==2.0.10 \
    pyparsing==3.1.0 \
    pysocks==1.7.1 \
    python-dateutil==2.8.2 \
    pytz==2023.3 \
    pywavelets==1.4.1 \
    PyYAML==5.3.1 \
    pyrender==0.1.45 \
    pysymbolic==1.0.2 \
    redis==4.5.5 \
    requests==2.31.0 \
    requests-oauthlib==1.3.1 \
    rich==13.4.2 \
    ruamel.yaml==0.18.5 \
    seaborn==0.13.1 \
    setuptools==59.5.0 \
    shapely==2.0.2 \
    sk-video==1.1.10 \
    spatialdyn==1.4.4 \
    tensorboard==2.14.0 \
    torchtyping==0.1.4 \
    tqdm==4.66.1 \
    typing==3.7.4.3 \
    tyro==0.6.3 \
    wandb==0.16.1

# Install box2d-py
RUN cd /home/$USER/ && \
    git clone https://github.com/pybox2d/pybox2d.git && \
    cd pybox2d && \
    python3 setup.py build && \
    python3 setup.py install

# Set up environment parameters
ENV USER=$USER
ENV HOME=/home/$USER/STAP
ENV PYTHONPATH=$PYTHONPATH:/home/$USER/STAP

COPY entrypoint.sh /
ENTRYPOINT ["/entrypoint.sh"] /
