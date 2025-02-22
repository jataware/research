FROM python:3.7-slim-buster

#assumes current repo has all submodules imported

# location of diplomacy bot repo
RUN mkdir /app
ADD . /app
WORKDIR /app

#linux dependancies
RUN apt update && apt upgrade
RUN apt install -y gcc git tree
RUN apt install -y wget dh-autoreconf build-essential libarchive-dev cryptsetup-bin squashfs-tools
RUN wget http://ftp.us.debian.org/debian/pool/main/libs/libseccomp/libseccomp2_2.5.3-2_amd64.deb && dpkg -i libseccomp2_2.5.3-2_amd64.deb
RUN wget https://github.com/sylabs/singularity/releases/download/v3.9.6/singularity-ce_3.9.6-focal_amd64.deb && dpkg -i singularity-ce_3.9.6-focal_amd64.deb


#install python libraries
# RUN pip install coloredlogs
# RUN pip install pytz
# RUN pip install bcrypt
# RUN pip install tqdm
# RUN pip install ujson
# RUN pip install tornado
# RUN pip install requests
# RUN pip install numpy
# RUN pip install protobuf
# RUN pip install pyyaml
# RUN pip install python-hostlist
# RUN pip install gym
# RUN pip install tensorflow==1.13.1
RUN pip install -r /app/requirements.txt

#install local version of research & diplomacy
RUN git clone https://github.com/jataware/diplomacy.git
RUN pip install /app/diplomacy

#download the benchmark model
#TBD

# envrionment variables for running
ENV WORKING_DIR="$HOME/tmp"
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=cpp

# run command to download the models
RUN python /app/diplomacy_research/scripts/launch_bot.py --download-models

#print out the working directory (ensuring we downloaded the models correctly)
RUN echo "contents of WORKING_DIR"
RUN tree $WORKING_DIR

#run command for starting the bot
#TODO->port/host/etc.
CMD ["python", "/app/diplomacy_research/scripts/launch_bot.py"]
