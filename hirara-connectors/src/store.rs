//! Atomic encrypted persistence. A process lock prevents stale concurrent writers.
use crate::net::{Error, fail};
use chacha20poly1305::{
    ChaCha20Poly1305, KeyInit,
    aead::{Aead, Payload},
};
use fs2::FileExt;
use rand::RngCore;
use rmcp::transport::auth::{AuthError, CredentialStore, StoredCredentials};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    fs::{File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    sync::{Arc, Mutex},
};

pub fn random_id() -> String {
    let mut b = [0u8; 24];
    rand::thread_rng().fill_bytes(&mut b);
    b.iter().map(|x| format!("{x:02x}")).collect()
}
#[derive(Clone, Serialize, Deserialize)]
pub struct Connection {
    pub id: String,
    pub owner: String,
    pub title: String,
    pub endpoint: String,
    pub allowed_tools: Vec<String>,
    pub mode: String,
    pub bearer: Option<String>,
    #[serde(default)]
    pub header_name: Option<String>,
    pub oauth: Option<StoredCredentials>,
    pub client_id: Option<String>,
}
impl Connection {
    pub fn public(&self) -> serde_json::Value {
        serde_json::json!({"connection_id":self.id,"title":self.title,"endpoint":self.endpoint,"auth":self.mode,"allowed_tools":self.allowed_tools,"configured":true,"has_credentials":self.mode=="none" || self.bearer.is_some() || self.oauth.as_ref().is_some_and(|x|x.token_response.is_some())})
    }
}
#[derive(Clone)]
pub struct Store {
    inner: Arc<Inner>,
}
struct Inner {
    path: PathBuf,
    cipher: ChaCha20Poly1305,
    records: Mutex<BTreeMap<String, Connection>>,
    _lock: File,
}
const AAD: &[u8] = b"Hirara connector vault v1";
impl Store {
    pub fn open(dir: &Path, key: &[u8; 32]) -> Result<Self, Error> {
        std::fs::create_dir_all(dir)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(dir, std::fs::Permissions::from_mode(0o700))?;
        }
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(dir.join("vault.lock"))?;
        lock.try_lock_exclusive()
            .map_err(|_| fail("connector vault is already in use"))?;
        let cipher = ChaCha20Poly1305::new(key.into());
        let path = dir.join("vault.bin");
        let records = if path.exists() {
            let metadata = std::fs::symlink_metadata(&path)?;
            if !metadata.is_file() || metadata.len() > 8 * 1024 * 1024 {
                return Err(fail("invalid connector vault"));
            }
            let bytes = std::fs::read(&path)?;
            if bytes.len() < 13 || bytes[0] != 1 {
                return Err(fail("invalid connector vault version"));
            }
            let plaintext = cipher
                .decrypt(
                    (&bytes[1..13]).into(),
                    Payload {
                        msg: &bytes[13..],
                        aad: AAD,
                    },
                )
                .map_err(|_| fail("cannot decrypt vault: wrong key or corrupted data"))?;
            serde_json::from_slice(&plaintext)?
        } else {
            BTreeMap::new()
        };
        Ok(Self {
            inner: Arc::new(Inner {
                path,
                cipher,
                records: Mutex::new(records),
                _lock: lock,
            }),
        })
    }
    pub fn list(&self, owner: &str) -> Vec<Connection> {
        self.inner
            .records
            .lock()
            .unwrap()
            .values()
            .filter(|x| x.owner == owner)
            .cloned()
            .collect()
    }
    pub fn get(&self, owner: &str, id: &str) -> Result<Connection, Error> {
        self.inner
            .records
            .lock()
            .unwrap()
            .get(id)
            .filter(|x| x.owner == owner)
            .cloned()
            .ok_or_else(|| fail("connection not found"))
    }
    fn persist(&self, records: &BTreeMap<String, Connection>) -> Result<(), Error> {
        let body = serde_json::to_vec(records)?;
        if body.len() > 8 * 1024 * 1024 - 1024 {
            return Err(fail("vault storage limit reached"));
        }
        let mut nonce = [0u8; 12];
        rand::thread_rng().fill_bytes(&mut nonce);
        let encrypted = self
            .inner
            .cipher
            .encrypt(
                (&nonce).into(),
                Payload {
                    msg: &body,
                    aad: AAD,
                },
            )
            .map_err(|_| fail("vault encryption failed"))?;
        let parent = self.inner.path.parent().unwrap();
        let mut tmp = tempfile::NamedTempFile::new_in(parent)?;
        tmp.write_all(&[1])?;
        tmp.write_all(&nonce)?;
        tmp.write_all(&encrypted)?;
        tmp.as_file().sync_all()?;
        tmp.persist(&self.inner.path)
            .map_err(|_| fail("vault write failed"))?;
        #[cfg(unix)]
        File::open(parent)?.sync_all()?;
        Ok(())
    }
    pub fn put(&self, connection: Connection) -> Result<(), Error> {
        let mut records = self.inner.records.lock().unwrap();
        if records.len() >= 256 && !records.contains_key(&connection.id) {
            return Err(fail("connection limit reached"));
        }
        let mut next = records.clone();
        next.insert(connection.id.clone(), connection);
        self.persist(&next)?;
        *records = next;
        Ok(())
    }
    pub fn delete(&self, owner: &str, id: &str) -> Result<(), Error> {
        let mut records = self.inner.records.lock().unwrap();
        if !records.get(id).is_some_and(|x| x.owner == owner) {
            return Err(fail("connection not found"));
        }
        let mut next = records.clone();
        next.remove(id);
        self.persist(&next)?;
        *records = next;
        Ok(())
    }
    pub fn credentials(&self, owner: &str, id: &str) -> VaultCredentials {
        VaultCredentials {
            store: self.clone(),
            owner: owner.into(),
            id: id.into(),
        }
    }
}
#[derive(Clone)]
pub struct VaultCredentials {
    store: Store,
    owner: String,
    id: String,
}
fn auth_error(_: impl std::fmt::Display) -> AuthError {
    AuthError::CredentialStoreError("encrypted credential store failed".into())
}
#[async_trait::async_trait]
impl CredentialStore for VaultCredentials {
    async fn load(&self) -> Result<Option<StoredCredentials>, AuthError> {
        Ok(self
            .store
            .get(&self.owner, &self.id)
            .map_err(auth_error)?
            .oauth)
    }
    async fn save(&self, credentials: StoredCredentials) -> Result<(), AuthError> {
        let mut record = self.store.get(&self.owner, &self.id).map_err(auth_error)?;
        record.oauth = Some(credentials);
        self.store.put(record).map_err(auth_error)
    }
    async fn clear(&self) -> Result<(), AuthError> {
        let mut record = self.store.get(&self.owner, &self.id).map_err(auth_error)?;
        record.oauth = None;
        self.store.put(record).map_err(auth_error)
    }
}
#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    pub fn record() -> Connection {
        Connection {
            id: "connection".into(),
            owner: "alice".into(),
            title: "test".into(),
            endpoint: "https://example.com/mcp".into(),
            allowed_tools: vec!["read".into()],
            mode: "bearer".into(),
            bearer: Some("very-secret-token".into()),
            header_name: None,
            oauth: None,
            client_id: None,
        }
    }
    #[test]
    fn encrypted_restart_and_isolation() {
        let dir = tempfile::tempdir().unwrap();
        let store = Store::open(dir.path(), &[7; 32]).unwrap();
        store.put(record()).unwrap();
        assert!(Store::open(dir.path(), &[7; 32]).is_err());
        assert!(store.get("bob", "connection").is_err());
        assert!(store.delete("bob", "connection").is_err());
        assert!(
            !String::from_utf8_lossy(&std::fs::read(dir.path().join("vault.bin")).unwrap())
                .contains("very-secret-token")
        );
        drop(store);
        assert!(Store::open(dir.path(), &[8; 32]).is_err());
        let store = Store::open(dir.path(), &[7; 32]).unwrap();
        assert_eq!(
            store.get("alice", "connection").unwrap().bearer.as_deref(),
            Some("very-secret-token")
        );
        store.delete("alice", "connection").unwrap();
        drop(store);
        assert!(
            Store::open(dir.path(), &[7; 32])
                .unwrap()
                .list("alice")
                .is_empty()
        );
    }
    #[test]
    fn tampering_fails_closed() {
        let dir = tempfile::tempdir().unwrap();
        let s = Store::open(dir.path(), &[0; 32]).unwrap();
        s.put(record()).unwrap();
        drop(s);
        let p = dir.path().join("vault.bin");
        let mut b = std::fs::read(&p).unwrap();
        b[20] ^= 1;
        std::fs::write(p, b).unwrap();
        assert!(Store::open(dir.path(), &[0; 32]).is_err());
    }
}
