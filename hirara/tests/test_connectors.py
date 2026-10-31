"""SDK forwards connector calls without accepting credentials or user identity."""
import httpx
import hirara
from hirara import Client


def test_connector_sdk_arguments_and_attribution():
    calls = []
    def handler(request):
        import json
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={'_hirara': {'attribution': 'This MCP connection is provided through Hirara.'}})
    client = Client('http://hub', local=False)
    client._client = httpx.Client(transport=httpx.MockTransport(handler), base_url='http://hub')
    try:
        client.connector_search('github', source='cursor')
        client.connector_details('cursor', 'github')
        client.connector_connect(endpoint='https://example.com/mcp')
        client.connector_connect('saved', reauthorize=True)
        client.connector_status()
        client.connector_tools('saved')
        result = client.connector_call('saved', 'read', {'query': 'test'})
        client.connector_disconnect('saved')
        assert result['_hirara']['attribution'].endswith('Hirara.')
        assert calls[2]['arguments'] == {'endpoint': 'https://example.com/mcp', 'reauthorize': False}
        assert calls[4]['arguments'] == {}
        assert calls[6]['arguments'] == {'connection_id': 'saved', 'tool_name': 'read', 'arguments': {'query': 'test'}}
        assert all(call['name'].startswith('connector_') for call in calls)
        for call in calls:
            assert not {'token', 'owner', 'user_id'} & call['arguments'].keys()
        assert callable(hirara.connector_connect)
    finally:
        client._client.close()
