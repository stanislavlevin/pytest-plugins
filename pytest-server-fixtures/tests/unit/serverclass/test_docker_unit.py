from mock import sentinel, patch, Mock

from pytest_server_fixtures.serverclass.docker import DockerServer

@patch('pytest_server_fixtures.serverclass.docker.ServerClass.__init__')
def test_init(mock_init):
    s = DockerServer(sentinel.server_type,
                     sentinel.get_cmd,
                     sentinel.env,
                     sentinel.image)

    mock_init.assert_called_with(sentinel.get_cmd, sentinel.env)

