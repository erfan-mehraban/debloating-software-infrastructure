import sys
import json
from docker import Client

docker_url = 'unix://var/run/docker.sock'
def import_images(newimgprfix):
    client = Client(base_url=docker_url)
    with open('{}.json'.format(newimgprfix)) as f:
        config = json.load(f)
        config = config['config']
        for key in config:
            print(key)
            with open('{}.tar'.format(key), 'rb') as tar:
                client.load_image(tar.read())

if __name__ == '__main__':
    import_images(*sys.argv[1:])
