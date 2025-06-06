from datetime import datetime
import gc
import os
import sys

import pandas as pd
from sqlalchemy import create_engine
from minio import Minio
from io import BytesIO
from airflow import DAG
from airflow.operators.python_operator import PythonOperator
from airflow.operators.dagrun_operator import TriggerDagRunOperator


def write_data_postgres(dataframe: pd.DataFrame) -> bool:
    """
    Dumps a Dataframe to the DBMS engine

    Parameters:
        - dataframe (pd.Dataframe) : The dataframe to dump into the DBMS engine

    Returns:
        - bool : True if the connection to the DBMS and the dump to the DBMS is successful, False if either
        execution is failed
    """
    db_config = {
        "dbms_engine": "postgresql",
        "dbms_username": "admin",
        "dbms_password": "admin",
        "dbms_ip": "data-warehouse",
        "dbms_port": "5432",
        "dbms_database": "nyc_warehouse",
        "dbms_table": "nyc_raw"
    }

    db_config["database_url"] = (
        f"{db_config['dbms_engine']}://{db_config['dbms_username']}:{db_config['dbms_password']}@"
        f"{db_config['dbms_ip']}:{db_config['dbms_port']}/{db_config['dbms_database']}"
    )
    try:
        engine = create_engine(db_config["database_url"])
        with engine.connect():
            success: bool = True
            print("Connection successful! Processing parquet file")
            dataframe.to_sql(db_config["dbms_table"], engine, index=False, if_exists='append')

    except Exception as e:
        success: bool = False
        print(f"Error connection to the database: {e}")
        return success

    return success


def clean_column_name(dataframe: pd.DataFrame) -> pd.DataFrame:
    """
    Take a Dataframe and rewrite it columns into a lowercase format.
    Parameters:
        - dataframe (pd.DataFrame) : The dataframe columns to change

    Returns:
        - pd.Dataframe : The changed Dataframe into lowercase format
    """
    dataframe.columns = map(str.lower, dataframe.columns)
    return dataframe


def dump_to_sql():
    client = Minio(
        "minio:9000",
        secure=False,
        access_key="minio",
        secret_key="minio123"
    )
    bucket_name = "bucket"
    parquet_files = [
        obj.object_name for obj in client.list_objects(bucket_name, recursive=True)
        if obj.object_name.endswith(".parquet")
    ]
    for parquet_file_name in parquet_files:
        data = client.get_object(bucket_name, parquet_file_name)
        parquet_df: pd.DataFrame = pd.read_parquet(BytesIO(data.read()))

        clean_column_name(parquet_df)
        if not write_data_postgres(parquet_df):
            del parquet_df
            gc.collect()
            return

        del parquet_df
        gc.collect()


with DAG(
    dag_id="tp2_dump_to_sql",
    description="Inject parquet files from Minio to PostgreSQL warehouse",
    schedule_interval=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["tp2", "warehouse", "minio"],
) as dag:
    
    run_etl = PythonOperator(
        task_id="transfer_minio_to_postgres",
        python_callable=dump_to_sql,
        provide_context=True,
    )
    
    trigger_tp3_dag = TriggerDagRunOperator(
        task_id="trigger_warehouse_to_datamart",
        trigger_dag_id="warehouse_to_datamart",
    )
    
    run_etl >> trigger_tp3_dag
