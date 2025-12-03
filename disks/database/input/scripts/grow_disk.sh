if sudo growpart /dev/sda 1; then
  sudo resize2fs /dev/sda1
else
  echo "Root partition cannot be grown"
fi
