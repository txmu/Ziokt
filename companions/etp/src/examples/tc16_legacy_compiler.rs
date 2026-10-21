//! Native Legacy frontend -> versioned Unified package, bounded JSONL input.
use std::io::{self, BufRead, Read, Write};
fn main() -> anyhow::Result<()> {
    let stdin = io::stdin();
    let mut input = stdin.lock();
    let mut output = io::stdout().lock();
    loop {
        let mut line = String::new();
        if input.by_ref().take(100001).read_line(&mut line)? == 0 {
            break;
        }
        anyhow::ensure!(line.len() <= 100000 && line.ends_with('\n'), "frame limit");
        let result = (|| -> anyhow::Result<serde_json::Value> {
            let value: serde_json::Value = serde_json::from_str(&line)?;
            let source = value["source"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("source string required"))?;
            etp_core::extensions::tc16_tcc::compile_legacy_unified(source)
        })();
        let frame = match result {
            Ok(value) => serde_json::json!({"ok":true,"result":value}),
            Err(error) => {
                serde_json::json!({"ok":false,"error":{"code":"ETP_LEGACY_COMPILE","message":error.to_string()}})
            }
        };
        serde_json::to_writer(&mut output, &frame)?;
        writeln!(output)?;
        output.flush()?;
    }
    Ok(())
}
