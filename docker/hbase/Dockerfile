# HBase Distributed Mode Docker Image
# Supports running as master, regionserver, or standalone

FROM eclipse-temurin:11-jre

ARG HBASE_VERSION=2.5.10
ARG HBASE_URL=https://archive.apache.org/dist/hbase/${HBASE_VERSION}/hbase-${HBASE_VERSION}-bin.tar.gz

ENV HBASE_HOME=/opt/hbase
ENV PATH="${HBASE_HOME}/bin:${PATH}"
ENV JAVA_HOME=/opt/java/openjdk

# Install required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Download and install HBase
RUN mkdir -p ${HBASE_HOME} && \
    curl -fSL "${HBASE_URL}" -o /tmp/hbase.tar.gz && \
    tar -xzf /tmp/hbase.tar.gz -C ${HBASE_HOME} --strip-components=1 && \
    rm /tmp/hbase.tar.gz && \
    mkdir -p ${HBASE_HOME}/logs

# Copy configuration files
COPY conf/hbase-site.xml ${HBASE_HOME}/conf/hbase-site.xml
COPY conf/hbase-env.sh ${HBASE_HOME}/conf/hbase-env.sh

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create data directory
RUN mkdir -p /data/hbase && chmod 777 /data/hbase

# HBase ports
# Master: 16000 (RPC), 16010 (Web UI)
# RegionServer: 16020 (RPC), 16030 (Web UI)
EXPOSE 16000 16010 16020 16030

WORKDIR ${HBASE_HOME}

ENTRYPOINT ["/entrypoint.sh"]
CMD ["help"]
