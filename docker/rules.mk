REGISTRY := ghcr.io
ORG := ossim-project

# HBase image configuration
HBASE_IMAGE := $(REGISTRY)/$(ORG)/hbase
HBASE_VERSION ?= 2.5.10
HBASE_TAG ?= $(HBASE_VERSION)
HBASE_DIR := $(dir $(lastword $(MAKEFILE_LIST)))hbase

.PHONY: docker-hbase build-docker-hbase hbase-push hbase-clean help


# HBase targets
docker-hbase: build-docker-hbase

build-docker-hbase:
	@echo "Building HBase image: $(HBASE_IMAGE):$(HBASE_TAG)"
	docker build -t $(HBASE_IMAGE):$(HBASE_TAG) \
		--build-arg HBASE_VERSION=$(HBASE_VERSION) \
		$(HBASE_DIR)
	docker tag $(HBASE_IMAGE):$(HBASE_TAG) $(HBASE_IMAGE):latest
	@echo "Built: $(HBASE_IMAGE):$(HBASE_TAG)"
	@echo "Tagged: $(HBASE_IMAGE):latest"

push-docker-hbase: build-docker-hbase
	@echo "Pushing HBase image to $(REGISTRY)"
	docker push $(HBASE_IMAGE):$(HBASE_TAG)
	docker push $(HBASE_IMAGE):latest

clean-docker-hbase:
	@echo "Removing HBase images"
	-docker rmi $(HBASE_IMAGE):$(HBASE_TAG) 2>/dev/null
	-docker rmi $(HBASE_IMAGE):latest 2>/dev/null

