import docker

client = docker.from_env()

print("Docker version info:")
print(client.version())

print("\nRunning a test container...")
output = client.containers.run("python:3.11-slim", "python --version", remove=True)
print("Container output:", output.decode().strip())