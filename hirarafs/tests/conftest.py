import json
import struct
import pytest

@pytest.fixture
def tiny_model(tmp_path):
    model=tmp_path/"model";model.mkdir()
    header=json.dumps({"embeddings":{"dtype":"F32","shape":[4,8],"data_offsets":[0,128]}})
    header+=" "*((-(8+len(header)))%8)
    vectors=[[0]*8,[1,0,0,0,0,0,0,0],[1,0,0,0,0,0,0,0],[0,1,0,0,0,0,0,0]]
    (model/"model.safetensors").write_bytes(struct.pack("<Q",len(header))+header.encode()+b"".join(struct.pack("<8f",*v) for v in vectors))
    tokenizer={"version":"1.0","truncation":None,"padding":None,"added_tokens":[],"normalizer":{"type":"Lowercase"},"pre_tokenizer":{"type":"Whitespace"},"post_processor":None,"decoder":None,"model":{"type":"WordLevel","vocab":{"[UNK]":0,"car":1,"automobile":2,"banana":3},"unk_token":"[UNK]"}}
    (model/"tokenizer.json").write_text(json.dumps(tokenizer))
    return model
