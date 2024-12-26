#!groovy

properties([disableConcurrentBuilds()])

pipeline {
    agent { label 'MLOPS' }
    // triggers { pollSCM('* * * * *') }
    options { timestamps() }
    environment { 
        OG_DISTR_PATH = credentials('OG_DISTR_PATH')
    }
    stages {

        stage('Build Docker Image') {
            when {
                branch 'master'
            }
            steps {
                sh 'docker build --no-cache -t document-reader .'
            }
        }

        stage('Save Docker Image') {
            when {
                branch 'master'
            }
            steps {
               // withCredentials([string(credentialsId: 'OG_DISTR_PATH', variable: 'OG_DISTR_PATH')]) {
                    sh '''docker save document-reader | gzip -c > "${OG_DISTR_PATH}/containers/document-reader.tgz"'''
                    sh 'chmod +x document-reader.sh'
                    sh '''cp document-reader.sh "${OG_DISTR_PATH}/containers/document-reader.sh"'''
                    sh '''cp docker-compose.yml "${OG_DISTR_PATH}/containers/document-reader.yml"'''
                //}
            }
        }

        stage('Execute') {
            when {
                anyOf {
                    branch 'dev'
                    branch 'master'
                }
            }
            steps {
                script {
                    
                    sh """
                        export STARTUP_COMMAND="bash -c \\"cd /app ; pip install --upgrade pip ; pip install -r requirements.txt ; python app.py\\""
                        docker-compose -p document-reader down --remove-orphans
                        docker-compose -p document-reader up -d --remove-orphans
                        docker-compose -p document-reader stop
                    """
                    def containerId = sh(script: "docker-compose -p document-reader ps -q document-reader", returnStdout: true).trim()
                    sh "docker cp ./ ${containerId}:/app"
                    sh 'docker-compose -p document-reader start'
                }
            }
        }
    }
}
