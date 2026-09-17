pipeline {
    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
        timestamps()
    }

    environment {
        // Manage SSH credentials safely via Jenkins Credentials Manager
        SSH_CRED_ID = 'flowsmith_ssh_key_user' 
    }

    stages {
        stage('Checkout') {
            when {
				branch 'production'
			}
            steps {
                checkout scm
            }
        }

        stage('Set Environment') {
            steps {
                script {
                    switch(env.BRANCH_NAME) {
                        case 'production':
                            env.ENVIRONMENT = 'PRODUCTION'
                            env.REMOTE_HOST = env.FLOWSMITH_HOST
                            env.REMOTE_USER = env.FLOWSMITH_SSHUSER
                            env.BASE_PATH   = env.FLOWSMITH_PATH
                            break
                        default:
                            error("Unsupported branch: ${env.BRANCH_NAME}")
                    }

                }
            }
        }

        stage('Production Approval') {
            steps {
                timeout(time: 30, unit: 'MINUTES') {
                    input message: "Deploy build ${env.BUILD_NUMBER} to PRODUCTION?", ok: "Deploy"
                }
            }
        }

        stage('Deploy & Launch Container') {
            steps {
                sshagent([env.SSH_CRED_ID]) {
                    // 1. Prepare directory structure on remote
                    sh """
                    ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST} '
                    '
                    """

                    // 2. Rsync app code and compose files to release folder
                    sh """
                    rsync -az --delete \
                        --exclude='__pycache__.*' \
                        --exclude='.git' \
                        --exclude='.env.production' \
                        --exclude='.env' \
                        --exclude='.claude' \
                        --exclude='.jenkins' \
                        --exclude='.vscode' \
                        --exclude='deployment_requirements.md' \
                        --exclude='Jenkinsfile' \
                        --exclude-from='.jenkins' \
                        -e "ssh -o StrictHostKeyChecking=no" \
                        ./ \
                        ${REMOTE_USER}@${REMOTE_HOST}:${BASE_PATH}/
                    """

                    // 3. Cd into release dir, trigger Compose & cleanup
                    sh """
                    ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST} '
                        cd ${BASE_PATH}
                        
                        # Build and launch new containers
                        docker compose up -d --build --force-recreate app
                                                
                        # Clean up unused Docker images to save disk space
                        docker image prune -f
                    '
                    """
                }
            }
        }
    }

    post {
        success { echo "Deployment successful." }
        failure { echo "Deployment failed." }
        always  { cleanWs() }
    }
}