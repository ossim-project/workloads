from pyspark.sql import SparkSession
from pyspark.sql.types import *
import time

# --- Step 1: Start SparkSession ---
spark = SparkSession.builder \
    .appName("TPC-DS Query 99 from HDFS") \
    .master("spark://controller:7077") \
    .config("spark.sql.shuffle.partitions", "64") \
    .config("spark.sql.adaptive.enabled", "true") \
    .getOrCreate()

# --- Step 2: Define schemas (for tables used in Q99 only) ---
schemas = {
    "web_sales": StructType([
        StructField("ws_sold_date_sk", IntegerType()),
        StructField("ws_sold_time_sk", IntegerType()),
        StructField("ws_ship_date_sk", IntegerType()),
        StructField("ws_item_sk", IntegerType()),
        StructField("ws_bill_customer_sk", IntegerType()),
        StructField("ws_bill_cdemo_sk", IntegerType()),
        StructField("ws_bill_hdemo_sk", IntegerType()),
        StructField("ws_bill_addr_sk", IntegerType()),
        StructField("ws_ship_customer_sk", IntegerType()),
        StructField("ws_ship_cdemo_sk", IntegerType()),
        StructField("ws_ship_hdemo_sk", IntegerType()),
        StructField("ws_ship_addr_sk", IntegerType()),
        StructField("ws_web_page_sk", IntegerType()),
        StructField("ws_web_site_sk", IntegerType()),
        StructField("ws_ship_mode_sk", IntegerType()),
        StructField("ws_warehouse_sk", IntegerType()),
        StructField("ws_promo_sk", IntegerType()),
        StructField("ws_order_number", IntegerType()),
        StructField("ws_quantity", IntegerType()),
        StructField("ws_wholesale_cost", DecimalType(7, 2)),
        StructField("ws_list_price", DecimalType(7, 2)),
        StructField("ws_sales_price", DecimalType(7, 2)),
        StructField("ws_ext_discount_amt", DecimalType(7, 2)),
        StructField("ws_ext_sales_price", DecimalType(7, 2)),
        StructField("ws_ext_wholesale_cost", DecimalType(7, 2)),
        StructField("ws_ext_list_price", DecimalType(7, 2)),
        StructField("ws_ext_tax", DecimalType(7, 2)),
        StructField("ws_coupon_amt", DecimalType(7, 2)),
        StructField("ws_ext_ship_cost", DecimalType(7, 2)),
        StructField("ws_net_paid", DecimalType(7, 2)),
        StructField("ws_net_paid_inc_tax", DecimalType(7, 2)),
        StructField("ws_net_paid_inc_ship", DecimalType(7, 2)),
        StructField("ws_net_paid_inc_ship_tax", DecimalType(7, 2)),
        StructField("ws_net_profit", DecimalType(7, 2)),
    ]),
    "warehouse": StructType([
        StructField("w_warehouse_sk", IntegerType()),
        StructField("w_warehouse_id", StringType()),
        StructField("w_warehouse_name", StringType()),
        StructField("w_warehouse_sq_ft", IntegerType()),
        StructField("w_street_number", StringType()),
        StructField("w_street_name", StringType()),
        StructField("w_street_type", StringType()),
        StructField("w_suite_number", StringType()),
        StructField("w_city", StringType()),
        StructField("w_county", StringType()),
        StructField("w_state", StringType()),
        StructField("w_zip", StringType()),
        StructField("w_country", StringType()),
        StructField("w_gmt_offset", FloatType()),
    ])
}

# --- Step 3: Register HDFS tables as temporary views ---
base_path = "hdfs:///bench/tpcds/raw/sf1"
for table, schema in schemas.items():
    path = f"{base_path}/{table}.dat"
    df = spark.read.option("delimiter", "|").schema(schema).csv(path)
    df.createOrReplaceTempView(table)
    print(f"✅ Loaded and registered: {table}")

# --- Step 4: TPC-DS Query 99 (simplified) ---
query_99 = """
SELECT
  ws.ws_order_number,
  ws.ws_warehouse_sk,
  ws.ws_ship_date_sk,
  w.w_warehouse_name
FROM
  web_sales ws
JOIN
  warehouse w ON ws.ws_warehouse_sk = w.w_warehouse_sk
WHERE
  ws.ws_ship_date_sk IS NOT NULL
LIMIT 100
"""

# --- Step 5: Run the query and time it ---
start = time.time()
result_df = spark.sql(query_99)
rows = result_df.count()
duration = time.time() - start

print(f"✅ Query 99 completed: {rows} rows in {duration:.2f} seconds")
result_df.show(20, truncate=False)

# Optional: Save to HDFS
# result_df.write.mode("overwrite").csv("hdfs:///results/tpcds_q99_output")

spark.stop()
