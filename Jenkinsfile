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
                            env.ENVIRONMENT  = 'STAGING'
                            env.COMPOSE_FILE = 'docker-compose.staging.yml'
                            env.REMOTE_HOST  = env.FLOWSMITH_HOST
                            env.REMOTE_USER  = env.FLOWSMITH_SSHUSER
                            env.BASE_PATH    = env.FLOWSMITH_PATH
                            break
                        case 'main':
                            env.ENVIRONMENT  = 'PRODUCTION'
                            env.COMPOSE_FILE = 'docker-compose.yml'
                            env.REMOTE_HOST  = env.FLOWSMITH_PROD_HOST ?: env.FLOWSMITH_HOST
                            env.REMOTE_USER  = env.FLOWSMITH_PROD_SSHUSER ?: env.FLOWSMITH_SSHUSER
                            env.BASE_PATH    = env.FLOWSMITH_PROD_PATH ?: env.FLOWSMITH_PATH
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
                    // StrictHostKeyChecking=accept-new trusts a host on first
                    // contact and rejects a changed key afterwards. For a
                    // regulated deployment, pin the host key with a Jenkins
                    // known_hosts credential and switch to =yes.
                    // 1. Ensure release directories exist on remote host
                    sh '''
                    set -euo pipefail
                    ssh -o StrictHostKeyChecking=accept-new "${REMOTE_USER}@${REMOTE_HOST}" \
                        "mkdir -p '${BASE_PATH}' '${BASE_PATH}/backups' '${BASE_PATH}/secrets'"
                    '''

                    // 2. Rsync app code and compose files to release folder without
                    // clobbering host-local env, backups, secrets, or credential files.
                    sh '''
                    set -euo pipefail
                    rsync -az --delete \
                        --exclude='__pycache__' \
                        --exclude='*.pyc' \
                        --exclude='.git' \
                        --exclude='.venv' \
                        --exclude='frontend/node_modules' \
                        --exclude='.env*' \
                        --exclude='backend/.env*' \
                        --exclude='hubspot.config.local.yml' \
                        --exclude='backups' \
                        --exclude='secrets' \
                        --exclude='deployment_requirements.md' \
                        --exclude='Jenkinsfile' \
                        -e "ssh -o StrictHostKeyChecking=accept-new" \
                        ./ \
                        "${REMOTE_USER}@${REMOTE_HOST}:${BASE_PATH}/"
                    '''

                    // 3. Run migrations, recreate app/worker, verify health/readyz, and prune old images
                    sh '''
                    set -euo pipefail
                    ssh -o StrictHostKeyChecking=accept-new "${REMOTE_USER}@${REMOTE_HOST}" \
                        "BASE_PATH='${BASE_PATH}' COMPOSE_FILE='${COMPOSE_FILE}' bash -s" <<'EOF'
set -euo pipefail
cd "$BASE_PATH"

docker compose -f "$COMPOSE_FILE" up -d postgres redis
docker compose -f "$COMPOSE_FILE" up --build --exit-code-from migrate migrate
docker compose -f "$COMPOSE_FILE" up -d --build --force-recreate app worker

APP_PORT_VAL="${APP_PORT:-8000}"
for i in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:${APP_PORT_VAL}/api/health" >/dev/null \
       && curl -sf "http://127.0.0.1:${APP_PORT_VAL}/api/readyz" >/dev/null; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Flowsmith failed health/readyz verification after deploy"
        docker compose -f "$COMPOSE_FILE" logs --tail=80 app worker
        exit 1
    fi
    sleep 2
done

docker image prune -f
EOF
                    '''
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