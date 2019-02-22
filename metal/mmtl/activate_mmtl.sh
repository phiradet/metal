export METALHOME="$( cd "$( dirname "../../${BASH_SOURCE[0]}" )" && pwd )"
export PYTHONPATH="$PYTHONPATH:$METALHOME"
echo "Added Snorkel MeTaL repository ($METALHOME) to \$PYTHONPATH."

export GLUEDATA="/dfs/scratch0/bradenjh/glue"
echo "Added data path ($GLUEDATA) to environment variables."

export CUDA_VISIBLE_DEVICES="0"
echo "Set CUDA_VISIBLE_DEVICES=0"

source "/dfs/scratch0/vschen/secrets/hazy_aws.sh"
echo "Added AWS keys to path."

VENVPATH="/dfs/scratch0/vschen/venv-mmtl"
source "$VENVPATH/bin/activate"
echo "Activated virtual environment ($VENVPATH)."
