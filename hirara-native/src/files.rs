//! Capability-relative operations: no ambient open of a caller's file path.
use crate::{number, text};
use cap_std::fs::{Dir, OpenOptions};
use serde_json::{Value, json};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};

fn parent(v: &Value, key: &str) -> Result<(Dir, String, PathBuf), String> {
    let raw = text(v, key)?;
    if raw.trim().is_empty() {
        return Err(format!("{key} is required"));
    }
    let absolute = if Path::new(raw).is_absolute() {
        PathBuf::from(raw)
    } else {
        std::env::current_dir()
            .map_err(|e| e.to_string())?
            .join(raw)
    };
    // Reject traversal rather than resolving through an untrusted symlink.
    if absolute
        .components()
        .any(|p| matches!(p, Component::ParentDir))
    {
        return Err("parent traversal (..) is not allowed".into());
    }
    let roots = v["roots"].as_array().ok_or("roots must be an array")?;
    let allowed: Vec<PathBuf> = roots
        .iter()
        .map(|r| {
            r.as_str()
                .ok_or("invalid root")
                .and_then(|s| std::fs::canonicalize(s).map_err(|_| "invalid filesystem root"))
        })
        .collect::<Result<_, _>>()
        .map_err(str::to_string)?;
    let root = if allowed.is_empty() {
        if v["allow_any_path"] != true {
            return Err("no filesystem roots configured".into());
        }
        Path::new("/").to_path_buf()
    } else {
        allowed
            .into_iter()
            .filter(|r| absolute.starts_with(r))
            .max_by_key(|r| r.components().count())
            .ok_or("path is outside allowed roots")?
    };
    let relative = absolute.strip_prefix(&root).map_err(|e| e.to_string())?;
    let leaf = relative
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or("path must name a file")?
        .to_owned();
    let base =
        Dir::open_ambient_dir(root, cap_std::ambient_authority()).map_err(|e| e.to_string())?;
    let relative_parent = relative
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(Path::new("."));
    let dir = base
        .open_dir(relative_parent)
        .map_err(|e| format!("cannot open parent within roots: {e}"))?;
    Ok((dir, leaf, absolute))
}

fn regular(dir: &Dir, name: &str) -> Result<(), String> {
    let m = dir.symlink_metadata(name).map_err(|e| e.to_string())?;
    if !m.is_file() || m.file_type().is_symlink() {
        return Err(
            "only regular files are supported; symlinks and directories are refused".into(),
        );
    }
    Ok(())
}

pub fn run(action: &str, v: &Value) -> Result<Value, String> {
    if v["allow_write"] != true {
        return Err("filesystem mutations disabled (CFS_ALLOW_WRITE=false)".into());
    }
    let (src, name, path) = parent(v, "path")?;
    regular(&src, &name)?;
    if action == "file_delete" {
        src.remove_file(&name).map_err(|e| e.to_string())?;
        return Ok(json!({"path":path,"deleted":true,"error":null}));
    }
    let mut request = v.clone();
    if action == "file_rename" {
        let new_name = text(v, "name")?;
        if new_name.is_empty()
            || new_name == "."
            || new_name == ".."
            || new_name.contains(['/', '\\'])
        {
            return Err("name must be a single filename".into());
        }
        request["dest"] = json!(path.parent().unwrap().join(new_name));
    }
    let (dst, dest_name, dest) = parent(&request, "dest")?;
    if path == dest {
        return Err("source and destination must differ".into());
    }
    let overwrite = v["overwrite"].as_bool().unwrap_or(false);
    if let Ok(m) = dst.symlink_metadata(&dest_name) {
        if !m.is_file() || m.file_type().is_symlink() {
            return Err("destination must be a regular file, not a symlink".into());
        }
        if !overwrite {
            return Err("destination exists (set overwrite=true)".into());
        }
    }
    if action != "file_copy" {
        // Atomic no-clobber rename on Linux. Cross-device moves fail, keeping source intact.
        #[cfg(target_os = "linux")]
        {
            use std::os::fd::AsFd;
            let flags = if overwrite {
                rustix::fs::RenameFlags::empty()
            } else {
                rustix::fs::RenameFlags::NOREPLACE
            };
            rustix::fs::renameat_with(src.as_fd(), &name, dst.as_fd(), &dest_name, flags).map_err(
                |e| format!("move failed (cross-filesystem moves are unsupported): {e}"),
            )?;
        }
        #[cfg(not(target_os = "linux"))]
        {
            if overwrite {
                src.rename(&name, &dst, &dest_name)
                    .map_err(|e| e.to_string())?;
            } else {
                src.hard_link(&name, &dst, &dest_name)
                    .map_err(|e| e.to_string())?;
                src.remove_file(&name)
                    .map_err(|e| format!("destination created but source removal failed: {e}"))?;
            }
        }
        return Ok(json!({"path":path,"dest":dest,"moved":true,"error":null}));
    }
    let cap = number(v, "max_bytes", 2_000_000)?;
    // open follows capabilities, never symlinks outside the root.
    let mut input = src.open(&name).map_err(|e| e.to_string())?;
    if !input.metadata().map_err(|e| e.to_string())?.is_file() {
        return Err("source is not a regular file".into());
    }
    if input.metadata().map_err(|e| e.to_string())?.len() > cap {
        return Err("copy exceeds CFS_MAX_WRITE_BYTES".into());
    }
    let mut opts = OpenOptions::new();
    opts.write(true).create_new(true);
    #[cfg(unix)]
    {
        use cap_std::fs::OpenOptionsExt;
        opts.mode(0o600);
    }
    let mut temp = None;
    for i in 0..100 {
        let candidate = format!(".hirara-copy-{}-{i}", std::process::id());
        match dst.open_with(&candidate, &opts) {
            Ok(f) => {
                temp = Some((candidate, f));
                break;
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e.to_string()),
        }
    }
    let (temp_name, mut output) = temp.ok_or("cannot create temporary copy")?;
    let result = (|| {
        let mut count = 0u64;
        let mut buffer = [0u8; 65536];
        loop {
            let n = input.read(&mut buffer).map_err(|e| e.to_string())?;
            if n == 0 {
                break;
            }
            count += n as u64;
            if count > cap {
                return Err("copy exceeds CFS_MAX_WRITE_BYTES".into());
            }
            output.write_all(&buffer[..n]).map_err(|e| e.to_string())?;
        }
        output.sync_all().map_err(|e| e.to_string())?;
        if overwrite {
            dst.rename(&temp_name, &dst, &dest_name)
                .map_err(|e| e.to_string())?;
        } else {
            dst.hard_link(&temp_name, &dst, &dest_name)
                .map_err(|e| e.to_string())?;
        }
        Ok(json!({"path":path,"dest":dest,"bytes_copied":count,"error":null}))
    })();
    let _ = dst.remove_file(&temp_name);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn permissions_and_lifecycle() {
        let root = tempfile::tempdir().unwrap();
        std::fs::write(root.path().join("a"), "hello").unwrap();
        let mut v = json!({"roots":[root.path()],"allow_write":true,"path":root.path().join("a"),"dest":root.path().join("b")});
        assert!(run("file_copy", &v).is_ok(), "{:?}", run("file_copy", &v));
        assert!(run("file_copy", &v).is_err());
        v["dest"] = json!(root.path().join("c"));
        assert!(run("file_move", &v).is_ok());
        assert!(!root.path().join("a").exists());
        v["path"] = v["dest"].clone();
        v["name"] = json!("d");
        assert!(run("file_rename", &v).is_ok());
        v["path"] = json!(root.path().join("d"));
        v["allow_write"] = json!(false);
        assert!(run("file_delete", &v).is_err());
        v["allow_write"] = json!(true);
        assert!(run("file_delete", &v).is_ok());
    }
    #[cfg(unix)]
    #[test]
    fn rejects_escape_and_symlinks() {
        let root = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        std::fs::write(outside.path().join("secret"), "secret").unwrap();
        std::os::unix::fs::symlink(outside.path(), root.path().join("escape")).unwrap();
        let v = json!({"roots":[root.path()],"allow_write":true,"path":root.path().join("escape/secret")});
        assert!(run("file_delete", &v).is_err());
        assert!(outside.path().join("secret").exists());
    }
}
