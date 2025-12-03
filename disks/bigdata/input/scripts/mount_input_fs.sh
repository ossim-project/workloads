#!/bin/bash

mount -t 9p -o trans=virtio,ro,cache=loose input_fsdev $1
