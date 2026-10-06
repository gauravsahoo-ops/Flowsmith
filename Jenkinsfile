pipeline {
    agent {
        label 'docker-jenkingsagent'
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '20'))
        disableConcurrentBuilds()
        timestamps()
    }

    triggers {
        // Automatically check Bitbucket every 2 minutes for new commits
        pollSCM('H/2 * * * *')
    }

    environment {
        // Manage SSH credentials safely via Jenkins Credentials Manager
        SSH_CRED_ID = 'flowsmith_ssh_key_user' 
    }

    stages {
        stage('Checkout') {
            when {
				branch 'staging'
			}
            steps {
                checkout scm
            }
        }

        stage('Set Environment') {
            steps {
                script {
                    switch(env.BRANCH_NAME) {
                        case 'staging':
                            env.ENVIRONMENT = 'STAGING'
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
                        --exclude='.vscode' \
                        --exclude='docker-compose.yml' \
                        --exclude='deployment_requirements.md' \
                        --exclude='Jenkinsfile' \
                        -e "ssh -o StrictHostKeyChecking=no" \
                        ./ \
                        ${REMOTE_USER}@${REMOTE_HOST}:${BASE_PATH}/
                    """

                    // 3. Cd into release dir, trigger Compose & cleanup
                    sh """
                    ssh -o StrictHostKeyChecking=no ${REMOTE_USER}@${REMOTE_HOST} '
                        cd ${BASE_PATH}

                        # Remove the currentl compose file if exists
                        if [ -f "docker-compose.yml" ]; then
                            rm -rf docker-compose.yml
                        fi

                        # Rename the compose file if it exists 
                        if [ -f "docker-compose.staging.yml" ]; then
                            mv docker-compose.staging.yml docker-compose.yml
                        fi
                        
                        # Build and launch new containers
                        docker compose up -d --build --force-recreate app worker
                                                
                        # Verify container code quality
                        docker compose exec -T app python -m ruff check app

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