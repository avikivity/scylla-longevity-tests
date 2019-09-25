#!groovy

def call(Map pipelineParams) {

    pipeline {
        agent {
            label {
                label getJenkinsLabels(params.backend, params.aws_region)
            }
        }
        parameters {
            string(defaultValue: "${pipelineParams.get('backend', 'aws')}",
               description: 'aws|gce',
               name: 'backend')

            string(defaultValue: "${pipelineParams.get('aws_region', 'eu-west-1')}",
               description: 'us-east-1|eu-west-1',
               name: 'aws_region')


            string(defaultValue: '', description: '', name: 'scylla_ami_id')
            string(defaultValue: '', description: '', name: 'scylla_version')
            string(defaultValue: '', description: '', name: 'scylla_repo')
            string(defaultValue: "${pipelineParams.get('provision_type', 'spot_low_price')}",
                   description: 'spot_low_price|on_demand|spot_fleet|spot_low_price|spot_duration',
                   name: 'provision_type')

            string(defaultValue: "${pipelineParams.get('post_behaviour', 'destroy')}",
                   description: 'keep|destroy',
                   name: 'post_behaviour')

            string(defaultValue: "${pipelineParams.get('tag_ami_with_result', 'false')}",
                   description: 'true|false',
                   name: 'tag_ami_with_result')
        }
        options {
            timestamps()
            disableConcurrentBuilds()
            timeout(pipelineParams.timeout)
            buildDiscarder(logRotator(numToKeepStr: '20'))
        }
        stages {
            stage('Checkout') {
               steps {
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
            stage('Run SCT Test') {
                steps {
                    script {
                        wrap([$class: 'BuildUser']) {
                            dir('scylla-cluster-tests') {

                                // handle params which can be a json list
                                def aws_region = groovy.json.JsonOutput.toJson(params.aws_region)
                                def test_config = groovy.json.JsonOutput.toJson(pipelineParams.test_config)

                                sh """
                                #!/bin/bash
                                set -xe
                                env

                                export SCT_CLUSTER_BACKEND="${params.backend}"
                                export SCT_REGION_NAME=${aws_region}
                                export SCT_CONFIG_FILES="${test_config}"

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

                                export SCT_FAILURE_POST_BEHAVIOR="${pipelineParams.params.get('post_behaviour', '')}"
                                export SCT_INSTANCE_PROVISION="${pipelineParams.params.get('provision_type', '')}"
                                export SCT_AMI_ID_DB_SCYLLA_DESC=\$(echo \$GIT_BRANCH | sed -E 's+(origin/|origin/branch-)++')
                                export SCT_AMI_ID_DB_SCYLLA_DESC=\$(echo \$SCT_AMI_ID_DB_SCYLLA_DESC | tr ._ - | cut -c1-8 )

                                export SCT_TAG_AMI_WITH_RESULT=${params.tag_ami_with_result}"

                                echo "start test ......."
                                ./docker/env/hydra.sh run-test ${pipelineParams.test_name} --backend ${params.backend}  --logdir /sct
                                echo "end test ....."
                                """
                            }
                        }
                    }
                }
            }
        }
    }

}
