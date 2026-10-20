//! Bounded JSONL differential runner; no network or host VM capabilities.
use base64::{engine::general_purpose::STANDARD, Engine};
use std::io::{self, BufRead, Read, Write};
fn main() -> anyhow::Result<()> {
    let stdin = io::stdin();
    let mut input = stdin.lock();
    let mut output = io::stdout().lock();
    loop {
        let mut line = String::new();
        if input.by_ref().take(100001).read_line(&mut line)? == 0 {
            break;
        };
        anyhow::ensure!(line.len() <= 100000 && line.ends_with('\n'), "frame limit");
        let value: serde_json::Value = serde_json::from_str(&line)?;
        let data = STANDARD.decode(
            value["package"]
                .as_str()
                .ok_or_else(|| anyhow::anyhow!("package"))?,
        )?;
        let budget = value["cycles"].as_u64().unwrap_or(10000) as usize;
        let result = etp_core::extensions::tc16_unified::execute_package(&data, budget)?;
        serde_json::to_writer(&mut output, &result)?;
        writeln!(output)?;
        output.flush()?;
    }
    Ok(())
}
