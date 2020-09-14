#!groovy

def completed_stages = [:]
def (testDuration, testRunTimeout, runnerTimeout, collectLogsTimeout, resourceCleanupTimeout) = [0,0,0,0,0]

def call(Map pipelineParams) {

    def builder = getJenkinsLabels(params.backend, params.aws_region)

    pipeline {
        agent {
            label {
                label builder.label
            }
        }
        environment {
            AWS_ACCESS_KEY_ID     = credentials('qa-aws-secret-key-id')
            AWS_SECRET_ACCESS_KEY = credentials('qa-aws-secret-access-key')
            SCT_TEST_ID = UUID.randomUUID().toString()
        }
        parameters {
            string(defaultValue: "${pipelineParams.get('backend', 'aws')}",
               description: 'aws|gce',
               name: 'backend')
            string(defaultValue: "${pipelineParams.get('aws_region', 'eu-west-1')}",
               description: 'Supported: us-east-1|eu-west-1|eu-west-2|eu-north-1|random (randomly select region)',
               name: 'aws_region')
            string(defaultValue: "a",
               description: 'Availability zone',
               name: 'availability_zone')


            string(defaultValue: '', description: '', name: 'scylla_ami_id')
            string(defaultValue: "${pipelineParams.get('scylla_version', '')}", description: '', name: 'scylla_version')
            string(defaultValue: '', description: '', name: 'scylla_repo')
            string(defaultValue: "${pipelineParams.get('provision_type', 'spot_low_price')}",
                   description: 'spot_low_price|on_demand|spot_fleet|spot_duration',
                   name: 'provision_type')

            string(defaultValue: "${pipelineParams.get('post_behavior_db_nodes', 'keep-on-failure')}",
                   description: 'keep|keep-on-failure|destroy',
                   name: 'post_behavior_db_nodes')
            string(defaultValue: "${pipelineParams.get('post_behavior_loader_nodes', 'destroy')}",
                   description: 'keep|keep-on-failure|destroy',
                   name: 'post_behavior_loader_nodes')
            string(defaultValue: "${pipelineParams.get('post_behavior_monitor_nodes', 'keep-on-failure')}",
                   description: 'keep|keep-on-failure|destroy',
                   name: 'post_behavior_monitor_nodes')

            string(defaultValue: "${pipelineParams.get('tag_ami_with_result', 'false')}",
                   description: 'true|false',
                   name: 'tag_ami_with_result')

            string(defaultValue: "${pipelineParams.get('ip_ssh_connections', 'private')}",
                   description: 'private|public|ipv6',
                   name: 'ip_ssh_connections')

            string(defaultValue: "${pipelineParams.get('scylla_mgmt_repo', '')}",
                   description: 'If empty - the default manager version will be taken',
                   name: 'scylla_mgmt_repo')

            string(defaultValue: "${pipelineParams.get('scylla_mgmt_agent_repo', '')}",
                   description: 'manager agent repo',
                   name: 'scylla_mgmt_agent_repo')

            string(defaultValue: "${pipelineParams.get('target_scylla_mgmt_server_repo', '')}",
                   description: 'Link to the repository of the manager that will be used as a target of the manager server in the manager upgrade test',
                   name: 'target_scylla_mgmt_server_repo')

            string(defaultValue: "${pipelineParams.get('target_scylla_mgmt_agent_repo', '')}",
                   description: 'Link to the repository of the manager that will be used as a target of the manager agents in the manager upgrade test',
                   name: 'target_scylla_mgmt_agent_repo')

            string(defaultValue: "'qa@scylladb.com','mgmt@scylladb.com'",
                   description: 'email recipients of email report',
                   name: 'email_recipients')

            string(defaultValue: "${pipelineParams.get('scylla_mgmt_pkg', '')}",
                   description: 'Url to the scylla manager packages',
                   name: 'scylla_mgmt_pkg')

            string(defaultValue: "${pipelineParams.get('test_config', '')}",
                   description: 'Test configuration file',
                   name: 'test_config')

            string(defaultValue: "${pipelineParams.get('test_name', '')}",
                   description: 'Name of the test to run',
                   name: 'test_name')
        }
        options {
            timestamps()
            disableConcurrentBuilds()
            timeout(pipelineParams.timeout)
            buildDiscarder(logRotator(numToKeepStr: '20'))
        }
        stages {
            stage('Checkout') {
                options {
                    timeout(time: 5, unit: 'MINUTES')
                }
                steps {
                    script {
                        completed_stages = [:]
                    }
                    dir('scylla-cluster-tests') {
                        checkout scm

                        dir("scylla-qa-internal") {
                            git(url: 'git@github.com:scylladb/scylla-qa-internal.git',
                                credentialsId:'b8a774da-0e46-4c91-9f74-09caebaea261',
                                branch: 'master')
                        }
                    }
               }
            }
            stage('Get test duration') {
                options {
                    timeout(time: 1, unit: 'MINUTES')
                }
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                dir('scylla-cluster-tests') {
                                    (testDuration, testRunTimeout, runnerTimeout, collectLogsTimeout, resourceCleanupTimeout) = getJobTimeouts(params, builder.region)
                                }
                            }
                        }
                    }
                }
            }
            stage('Create SCT Runner') {
                options {
                    timeout(time: 5, unit: 'MINUTES')
                }
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                dir('scylla-cluster-tests') {
                                    createSctRunner(params, runnerTimeout , builder.region)
                                }
                            }
                        }
                    }
                }
            }
            stage('Run SCT Test') {
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                timeout(time: testRunTimeout, unit: 'MINUTES') {
                                    dir('scylla-cluster-tests') {

                                        // handle params which can be a json list
                                        def aws_region = initAwsRegionParam(params.aws_region, builder.region)
                                        def test_config = groovy.json.JsonOutput.toJson(params.test_config)
                                        def cloud_provider = params.backend.trim().toLowerCase()

                                        sh """
                                        #!/bin/bash
                                        set -xe
                                        env
                                        rm -fv ./latest

                                        export SCT_CLUSTER_BACKEND="${params.backend}"
                                        export SCT_REGION_NAME=${aws_region}
                                        export SCT_CONFIG_FILES=${test_config}
                                        export SCT_COLLECT_LOGS=false

                                        if [[ ! -z "${params.scylla_ami_id}" ]] ; then
                                            export SCT_AMI_ID_DB_SCYLLA="${params.scylla_ami_id}"
                                        elif [[ ! -z "${params.scylla_version}" ]] ; then
                                            export SCT_SCYLLA_VERSION="${params.scylla_version}"
                                        elif [[ ! -z "${params.scylla_repo}" ]] ; then
                                            export SCT_SCYLLA_REPO="${params.scylla_repo}"
                                        else
                                            echo "need to choose one of SCT_AMI_ID_DB_SCYLLA | SCT_SCYLLA_VERSION | SCT_SCYLLA_REPO"
                                            exit 1
                                        fi

                                        export SCT_POST_BEHAVIOR_DB_NODES="${params.post_behavior_db_nodes}"
                                        export SCT_POST_BEHAVIOR_LOADER_NODES="${params.post_behavior_loader_nodes}"
                                        export SCT_POST_BEHAVIOR_MONITOR_NODES="${params.post_behavior_monitor_nodes}"
                                        export SCT_INSTANCE_PROVISION="${pipelineParams.params.get('provision_type', '')}"
                                        export SCT_AMI_ID_DB_SCYLLA_DESC=\$(echo \$GIT_BRANCH | sed -E 's+(origin/|origin/branch-)++')
                                        export SCT_AMI_ID_DB_SCYLLA_DESC=\$(echo \$SCT_AMI_ID_DB_SCYLLA_DESC | tr ._ - | cut -c1-8 )

                                        export SCT_TAG_AMI_WITH_RESULT="${params.tag_ami_with_result}"
                                        export SCT_IP_SSH_CONNECTIONS="${params.ip_ssh_connections}"

                                        if [[ ! -z "${params.scylla_mgmt_repo}" ]] ; then
                                            export SCT_SCYLLA_MGMT_REPO="${params.scylla_mgmt_repo}"
                                        fi

                                        if [[ ! -z "${params.target_scylla_mgmt_server_repo}" ]] ; then
                                            export SCT_TARGET_SCYLLA_MGMT_SERVER_REPO="${params.target_scylla_mgmt_server_repo}"
                                        fi

                                        if [[ ! -z "${params.target_scylla_mgmt_agent_repo}" ]] ; then
                                            export SCT_TARGET_SCYLLA_MGMT_AGENT_REPO="${params.target_scylla_mgmt_agent_repo}"
                                        fi

                                        if [[ ! -z "${params.scylla_mgmt_agent_repo}" ]] ; then
                                            export SCT_SCYLLA_MGMT_AGENT_REPO="${params.scylla_mgmt_agent_repo}"
                                        fi

                                        if [[ ! -z "${params.scylla_mgmt_pkg}" ]] ; then
                                            export SCT_SCYLLA_MGMT_PKG="${params.scylla_mgmt_pkg}"
                                        fi

                                        echo "start test ......."
                                        if [[ "$cloud_provider" == "aws" ]]; then
                                            SCT_RUNNER_IP=\$(cat sct_runner_ip||echo "")
                                            if [[ ! -z "\${SCT_RUNNER_IP}" ]] ; then
                                                ./docker/env/hydra.sh --execute-on-runner \${SCT_RUNNER_IP} run-test ${params.test_name} --backend ${params.backend}
                                            else
                                                echo "SCT runner IP file is empty. Probably SCT Runner was not created."
                                                exit 1
                                            fi
                                        else
                                            ./docker/env/hydra.sh run-test ${params.test_name} --backend ${params.backend}  --logdir "`pwd`"
                                        fi
                                        echo "end test ....."
                                        """
                                    }
                                }
                            }
                        }
                    }
                }
            }
            stage("Collect log data") {
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                dir('scylla-cluster-tests') {
                                    timeout(time: collectLogsTimeout, unit: 'MINUTES') {
                                        runCollectLogs(params, builder.region)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            stage('Clean resources') {
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                dir('scylla-cluster-tests') {
                                    timeout(time: resourceCleanupTimeout, unit: 'MINUTES') {
                                        runCleanupResource(params, builder.region)
                                        completed_stages['clean_resources'] = true
                                    }
                                }
                            }
                        }
                    }
                }
            }
            stage("Send email with result") {
                options {
                    timeout(time: 10, unit: 'MINUTES')
                }
                steps {
                    catchError(stageResult: 'FAILURE') {
                        script {
                            wrap([$class: 'BuildUser']) {
                                dir('scylla-cluster-tests') {
                                    runSendEmail(params, currentBuild)
                                    completed_stages['send_email'] = true
                                }
                            }
                        }
                    }
                }
            }
        }
        post {
            always {
                script {
                    // jenkins artifacts are not available anymore - so we need to copy them
                    try {

                        dir('scylla-cluster-tests') {
                            sh "rm -rf logs"
                            copyLogsFromSctRunner('logs')
                            archiveArtifacts artifacts: 'logs/**'
                            sh "rm -rf logs"
                        }
                    } catch (Exception err) {
                        echo err.getMessage()
                        echo "Error detected during archiveArtifacts, but we will continue."
                    }

                    def collect_logs = completed_stages['collect_logs']
                    def clean_resources = completed_stages['clean_resources']
                    def send_email = completed_stages['send_email']
                    sh """
                        echo "$collect_logs"
                        echo "$clean_resources"
                        echo "$send_email"
                    """
                    if (!completed_stages['clean_resources']) {
                        catchError {
                            script {
                                wrap([$class: 'BuildUser']) {
                                    dir('scylla-cluster-tests') {
                                        timeout(time: resourceCleanupTimeout, unit: 'MINUTES') {
                                            runCleanupResource(params, builder.region)
                                        }
                                    }
                                }
                            }
                        }
                    }
                    if (!completed_stages['send_email']) {
                        catchError {
                            script {
                                wrap([$class: 'BuildUser']) {
                                    dir('scylla-cluster-tests') {
                                        timeout(time: 10, unit: 'MINUTES') {
                                            runSendEmail(params, currentBuild)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

}
