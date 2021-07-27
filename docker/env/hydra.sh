#!/usr/bin/env bash
set -e
CMD=$@
DOCKER_ENV_DIR=$(readlink -f "$0")
DOCKER_ENV_DIR=$(dirname "${DOCKER_ENV_DIR}")
DOCKER_REPO=scylladb/hydra
SCT_DIR=$(dirname "${DOCKER_ENV_DIR}")
SCT_DIR=$(dirname "${SCT_DIR}")
VERSION=v$(cat "${DOCKER_ENV_DIR}/version")
WORK_DIR=/sct
HOST_NAME=SCT-CONTAINER
RUN_BY_USER=$(python3 "${SCT_DIR}/sdcm/utils/get_username.py")
USER_ID=$(id -u "${USER}")
HOME_DIR=${HOME}

SCT_RUNNER_IP=""
HYDRA_DRY_RUN=""

export SCT_TEST_ID=${SCT_TEST_ID:-$(uuidgen)}
export GIT_USER_EMAIL=$(git config --get user.email)

# Hydra arguments parsing

while [[ $# -gt 0 ]]; do
    case $1 in
        --execute-on-runner)
            SCT_RUNNER_IP="$2"
            shift
            shift
            ;;
        --dry-run-hydra)
            HYDRA_DRY_RUN="1"
            shift
            ;;
        -*|--*)
            echo "Unknown argument '$1'"
            exit 1
            shift
            shift
            ;;
        *)
            break
            ;;
    esac
done

# Hydra command arguments line parsing

HYDRA_COMMAND=()

while [[ $# -gt 0 ]]; do
    case $1 in
        -b|--backend)
            SCT_CLUSTER_BACKEND="$2"
            HYDRA_COMMAND+=("$1")
            HYDRA_COMMAND+=("$2")
            shift
            shift
            ;;
        *)
            HYDRA_COMMAND+=("$1")
            shift
            ;;
    esac
done

# if running on Build server
if [[ ${USER} == "jenkins" ]]; then
    echo "Running on Build Server..."
    HOST_NAME=`hostname`
else
    TTY_STDIN="-it"
    TPUT_OPTIONS=""
    [[ -z "$TERM" || "$TERM" == 'dumb' ]] && TPUT_OPTIONS="-T xterm-256color"
    TERM_SET_SIZE="export COLUMNS=`tput $TPUT_OPTIONS cols`; export LINES=`tput $TPUT_OPTIONS lines`;"
fi

if ! docker --version; then
    echo "Docker not installed!!! Please run 'install-hydra.sh'!"
    exit 1
fi

if [[ ${USER} == "jenkins" || -z "`docker images ${DOCKER_REPO}:${VERSION} -q`" ]]; then
    echo "Pull version $VERSION from Docker Hub..."
    docker pull ${DOCKER_REPO}:${VERSION}
else
    echo "There is ${DOCKER_REPO}:${VERSION} in local cache, use it."
fi

# Check for SSH keys
if [ -z "$HYDRA_DRY_RUN" ]; then
    ${SCT_DIR}/get-qa-ssh-keys.sh
else
    echo ${SCT_DIR}/get-qa-ssh-keys.sh
fi

# change ownership of results directories
echo "Making sure the ownerships of results directories are of the user"
if [ -z "$HYDRA_DRY_RUN" ]; then
    sudo chown -R `whoami`:`whoami` ~/sct-results &> /dev/null || true
    sudo chown -R `whoami`:`whoami` "${SCT_DIR}/sct-results" &> /dev/null || true
else
    echo "sudo chown -R `whoami`:`whoami` ~/sct-results &> /dev/null || true"
    echo "sudo chown -R `whoami`:`whoami` \"${SCT_DIR}/sct-results\" &> /dev/null || true"
fi

# export all SCT_* env vars into the docker run
SCT_OPTIONS=$(env | grep SCT_ | cut -d "=" -f 1 | xargs -i echo "--env {}")

# export all BUILD_* env vars into the docker run
BUILD_OPTIONS=$(env | grep BUILD_ | cut -d "=" -f 1 | xargs -i echo "--env {}")

# export all AWS_* env vars into the docker run
AWS_OPTIONS=$(env | grep AWS_ | cut -d "=" -f 1 | xargs -i echo "--env {}")

# export all JENKINS_* env vars into the docker run
JENKINS_OPTIONS=$(env | grep JENKINS_ | cut -d "=" -f 1 | xargs -i echo "--env {}")

function run_in_docker () {
    CMD_TO_RUN=$1
    REMOTE_DOCKER_HOST=$2
    echo "Going to run '${CMD_TO_RUN}'..."
    if [ -z "$HYDRA_DRY_RUN" ]; then
        docker ${REMOTE_DOCKER_HOST} run --rm ${TTY_STDIN} --privileged \
            -h ${HOST_NAME} \
            -l "TestId=${SCT_TEST_ID}" \
            -l "RunByUser=${RUN_BY_USER}" \
            -v /var/run:/run \
            -v "${SCT_DIR}:${SCT_DIR}" \
            -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
            -v /tmp:/tmp \
            -v /var/tmp:/var/tmp \
            -v "${HOME_DIR}:${HOME_DIR}" \
            -v /etc/passwd:/etc/passwd:ro \
            -v /etc/group:/etc/group:ro \
            -v /etc/sudoers:/etc/sudoers:ro \
            -v /etc/sudoers.d/:/etc/sudoers.d:ro \
            -v /etc/shadow:/etc/shadow:ro \
            -w "${SCT_DIR}" \
            -e JOB_NAME="${JOB_NAME}" \
            -e BUILD_URL="${BUILD_URL}" \
            -e BUILD_NUMBER="${BUILD_NUMBER}" \
            -e _SCT_BASE_DIR="${SCT_DIR}" \
            -e GIT_USER_EMAIL \
            -u ${USER_ID} \
            ${DOCKER_GROUP_ARGS[@]} \
            ${SCT_OPTIONS} \
            ${BUILD_OPTIONS} \
            ${JENKINS_OPTIONS} \
            ${AWS_OPTIONS} \
            --net=host \
            --name="${SCT_TEST_ID}_$(date +%s)" \
            ${DOCKER_REPO}:${VERSION} \
            /bin/bash -c "sudo ln -s '${SCT_DIR}' '${WORK_DIR}'; /sct/get-qa-ssh-keys.sh; ${TERM_SET_SIZE} eval '${CMD_TO_RUN}'"
    else
        echo docker ${REMOTE_DOCKER_HOST} run --rm ${TTY_STDIN} --privileged \
            -h ${HOST_NAME} \
            -l "TestId=${SCT_TEST_ID}" \
            -l "RunByUser=${RUN_BY_USER}" \
            -v /var/run:/run \
            -v "${SCT_DIR}:${SCT_DIR}" \
            -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
            -v /tmp:/tmp \
            -v /var/tmp:/var/tmp \
            -v "${HOME_DIR}:${HOME_DIR}" \
            -v /etc/passwd:/etc/passwd:ro \
            -v /etc/group:/etc/group:ro \
            -v /etc/sudoers:/etc/sudoers:ro \
            -v /etc/sudoers.d/:/etc/sudoers.d:ro \
            -v /etc/shadow:/etc/shadow:ro \
            -w "${SCT_DIR}" \
            -e JOB_NAME="${JOB_NAME}" \
            -e BUILD_URL="${BUILD_URL}" \
            -e BUILD_NUMBER="${BUILD_NUMBER}" \
            -e _SCT_BASE_DIR="${SCT_DIR}" \
            -e GIT_USER_EMAIL \
            -u ${USER_ID} \
            ${DOCKER_GROUP_ARGS[@]} \
            ${SCT_OPTIONS} \
            ${BUILD_OPTIONS} \
            ${JENKINS_OPTIONS} \
            ${AWS_OPTIONS} \
            --net=host \
            --name="${SCT_TEST_ID}_$(date +%s)" \
            ${DOCKER_REPO}:${VERSION} \
            /bin/bash -c "sudo ln -s '${SCT_DIR}' '${WORK_DIR}'; /sct/get-qa-ssh-keys.sh; ${TERM_SET_SIZE} eval '${CMD_TO_RUN}'"
    fi
}

if [[ -n "$SCT_RUNNER_IP" ]]; then
    if [[ ! "$SCT_RUNNER_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "=========================================================================================================="
        echo "Invalid IP provided for '--execute-on-runner'. Run 'hydra create-runner-instance' or check ./sct_runner_ip"
        echo "=========================================================================================================="
        exit 2
    fi
    echo "SCT Runner IP: $SCT_RUNNER_IP"

    if [ -z "$HYDRA_DRY_RUN" ]; then
        eval $(ssh-agent)
    else
        echo 'eval $(ssh-agent)'
    fi

    function clean_ssh_agent {
        echo "Cleaning SSH agent"
        if [ -z "$HYDRA_DRY_RUN" ]; then
            eval $(ssh-agent -k)
        else
            echo 'eval $(ssh-agent -k)'
        fi
    }

    trap clean_ssh_agent EXIT

    if [ -z "$HYDRA_DRY_RUN" ]; then
        ssh-add ~/.ssh/scylla-qa-ec2
        ssh-add ~/.ssh/scylla-test
    else
        echo ssh-add ~/.ssh/scylla-qa-ec2
        echo ssh-add ~/.ssh/scylla-test
    fi

    echo "Going to run a Hydra commands on SCT runner '$SCT_RUNNER_IP'..."
    HOME_DIR="/home/ubuntu"

    echo "Syncing ${SCT_DIR} to the SCT runner instance..."
    if [ -z "$HYDRA_DRY_RUN" ]; then
        ssh-keygen -R "$SCT_RUNNER_IP" || true
        rsync -ar -e 'ssh -o StrictHostKeyChecking=no' --delete ${SCT_DIR} ubuntu@${SCT_RUNNER_IP}:/home/ubuntu/
    else
        echo "ssh-keygen -R \"$SCT_RUNNER_IP\" || true"
        echo "rsync -ar -e 'ssh -o StrictHostKeyChecking=no' --delete ${SCT_DIR} ubuntu@${SCT_RUNNER_IP}:/home/ubuntu/"
    fi
    if [[ -z "$AWS_OPTIONS" ]]; then
        echo "AWS credentials were not passed using AWS_* environment variables!"
        echo "Checking if ~/.aws/credentials exists..."
        if [ ! -f ~/.aws/credentials ]; then
            echo "Can't run SCT without AWS credentials!"
            exit 1
        fi
        echo "AWS credentials file found. Syncing to SCT Runner..."
        if [ -z "$HYDRA_DRY_RUN" ]; then
            rsync -ar -e 'ssh -o StrictHostKeyChecking=no' --delete ~/.aws ubuntu@${SCT_RUNNER_IP}:/home/ubuntu/
        else
            echo "rsync -ar -e 'ssh -o StrictHostKeyChecking=no' --delete ~/.aws ubuntu@${SCT_RUNNER_IP}:/home/ubuntu/"
        fi
    else
        echo "AWS_* environment variables found and will passed to Hydra container."
    fi

    # Only copy GCE credential for GCE backend
    if [[ "${SCT_CLUSTER_BACKEND}" =~ "gce" || "${SCT_CLUSTER_BACKEND}" =~ "gke" ]]; then
        if [ -f ~/.google_libcloud_auth.skilled-adapter-452 ]; then
            echo "GCE credentials file found. Syncing to SCT Runner..."
            if [ -z "$HYDRA_DRY_RUN" ]; then
                rsync -ar -e 'ssh -o StrictHostKeyChecking=no' --delete ~/.google_libcloud_auth.skilled-adapter-452 ubuntu@${SCT_RUNNER_IP}:/home/ubuntu/
            else
                echo "rsync -ar -e 'ssh -o StrictHostKeyChecking=no' --delete ~/.google_libcloud_auth.skilled-adapter-452 ubuntu@${SCT_RUNNER_IP}:/home/ubuntu/"
            fi
        else
            echo "GCE backend is used, but no gcloud token found !!!"
        fi
    fi

    SCT_DIR="/home/ubuntu/scylla-cluster-tests"
    USER_ID=1000
    if [ -z "${DOCKER_GROUP_ARGS[@]}" ]; then
        for gid in $(ssh -o StrictHostKeyChecking=no ubuntu@${SCT_RUNNER_IP} id -G); do
            DOCKER_GROUP_ARGS+=(--group-add "$gid")
        done
    fi

    DOCKER_HOST="-H ssh://ubuntu@${SCT_RUNNER_IP}"
else
    if [ -z "${DOCKER_GROUP_ARGS[@]}" ]; then
        for gid in $(id -G); do
            DOCKER_GROUP_ARGS+=(--group-add "$gid")
        done
    fi
fi

COMMAND=${HYDRA_COMMAND[0]}

if [[ "$COMMAND" == *'bash'* ]] || [[ "$COMMAND" == *'python'* ]]; then
    CMD=${HYDRA_COMMAND[@]}
else
    CMD="./sct.py ${HYDRA_COMMAND[@]}"
fi

run_in_docker "${CMD}" "${DOCKER_HOST}"
