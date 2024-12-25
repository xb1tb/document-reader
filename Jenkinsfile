pipeline {
    agent any

    stages {

        stage('Build Docker Image') {
            when {
                branch 'master'
            }
            steps {
                script {
                    // Build the document reader image
                    sh 'docker build --no-cache -t document-reader .'
                }
            }
        }

        stage('Save Docker Image') {
            when {
                branch 'master'
            }
            steps {
                script {
                    // Save Docker image and other necessary files
                    sh '''docker save document-reader | gzip -c > ${env.OG_DISTR_PATH}/containers/document-reader.tgz'''
                    sh 'chmod +x document-reader.sh'
                    sh '''cp document-reader.sh ${env.OG_DISTR_PATH}/containers/document-reader.sh'''
                    sh '''cp docker-compose.yml ${env.OG_DISTR_PATH}/containers/document-reader.yml'''
                }
            }
        }

        stage('Execute') {
            when {
                branch 'dev'
            }
            steps {
                script {
                    // Execute Docker Compose commands
                    sh '''export STARTUP_COMMAND="bash -c \\"cd /app ; pip install --upgrade pip ; pip install -r requirements.txt ; python app.py\\""
                    docker-compose -p document-reader down --remove-orphans
                    docker-compose -p document-reader up -d --remove-orphans
                    docker-compose -p document-reader stop
                    docker cp ./ "$(docker-compose -p document-reader ps -q document-reader)":/app
                    docker-compose -p document-reader start'''
                }
            }
        }   
    }
}