FROM  registry.bohrium.dp.tech/dptech/abacus-stable:LTSv3.10


RUN  curl -LsSf https://astral.sh/uv/install.sh | sh


RUN git clone https://github.com/MCresearch/aiida-abacus.git


RUN uv venv && pip install -e ./aiida-abacus
