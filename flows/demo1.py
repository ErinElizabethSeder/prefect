from prefect import flow, get_run_logger, tags, variables
from prefect import task
from prefect_aws import MinIOCredentials
from prefect_aws.s3 import S3Bucket

from datetime import timedelta
import requests

from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.linear_model import ElasticNet

import pandas as pd
import numpy as np
import mlflow
import mlflow.sklearn
from mlflow.models import infer_signature

import os


@task
def fetch_data():

    minio_credentials = MinIOCredentials(
       minio_root_user = "minio",
       minio_root_password = "minio123"
    )
    s3_client = minio_credentials.get_boto3_session().client(
       service_name="s3",
       endpoint_url="http://10.30.8.137:9000"
    )

    s3_client.download_file(Bucket="test1", Key="winequality-white.csv", Filename="winequality-white.csv")
    data = pd.read_csv("winequality-white.csv")
    # data = data.iloc[: , 1:]
    return data


def eval_metrics(actual, pred):
    rmse = np.sqrt(mean_squared_error(actual, pred))
    mae = mean_absolute_error(actual, pred)
    r2 = r2_score(actual, pred)
    return rmse, mae, r2

@task
def train_model(logger, data, mlflow_experiment_id, alpha=0.5, l1_ratio=0.5):
    mlflow.set_tracking_uri(variables.get('mlflow_tracking_uri'))
    train, test = train_test_split(data)

    # The predicted column is "quality" which is a scalar from [3, 9]
    train_x = train.drop(["quality"], axis=1)
    test_x = test.drop(["quality"], axis=1)
    train_y = train[["quality"]]
    test_y = test[["quality"]]

    with mlflow.start_run(experiment_id=mlflow_experiment_id):
        lr = ElasticNet(alpha=alpha, l1_ratio=l1_ratio, random_state=42)
        lr.fit(train_x, train_y)
        predicted_qualities = lr.predict(test_x)
        (rmse, mae, r2) = eval_metrics(test_y, predicted_qualities)

        logger.info("Elasticnet model (alpha=%f, l1_ratio=%f):" % (alpha, l1_ratio))
        logger.info("  RMSE: %s" % rmse)
        logger.info("  MAE: %s" % mae)
        logger.info("  R2: %s" % r2)

        mlflow.log_param("alpha", alpha)
        mlflow.log_param("l1_ratio", l1_ratio)
        mlflow.log_metric("rmse", rmse)
        mlflow.log_metric("r2", r2)
        mlflow.log_metric("mae", mae)

        #mlflow.sklearn.log_model(lr, "model")
    # Infer the model signature
        y_pred = lr.predict(test_x)
        signature = infer_signature(test_x, y_pred)
        logger.info("  sign: %s" % signature )
    # Log the sklearn model and register as version 1
        mlflow.sklearn.log_model(
            sk_model=lr,
            artifact_path="sklearn-model",
            signature=signature,
            registered_model_name="demo-linear-regression-model",
        )
    

@flow
def demo_pipeline1(mlflow_experiment_id: int, alpha: float = 0.5, l1_ratio: float = 0.5):
    data = fetch_data()

    logger = get_run_logger()
    logger.info(f"minIO data: {data.head(10)}!")

    train_model(logger=logger, data=data, mlflow_experiment_id=mlflow_experiment_id, alpha=alpha, l1_ratio=l1_ratio)
if __name__ == "__main__":
    demo_pipeline1()
