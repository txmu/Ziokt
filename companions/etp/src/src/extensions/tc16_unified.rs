//! TC-16 Unified v1 interpreter. Independent from the legacy ETP VM.
//! No MMIO, filesystem, network, providers or contract storage capabilities.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
type VmResult<T> = Result<T, &'static str>;
const OPS: [&str; 44] = [
    "HALT", "MOV", "MOVI", "LOAD", "STORE", "LOADB", "STOREB", "ADD", "SUB", "AND", "OR", "XOR",
    "NOT", "INC", "DEC", "CMP", "SHL", "SHR", "SWAP", "PUSH", "POP", "JMP", "JZ", "JC", "JP", "JO",
    "CALL", "RET", "BCDADD", "BCDSUB", "SETFLAG", "CLRFLAG", "SETMODE", "SYS", "NOP", "MUL", "DIV",
    "RETI", "EI", "DI", "GETSP", "SETSP", "JNZ", "PARITY",
];
struct Cpu {
    r: [u16; 16],
    memory: Vec<u8>,
    pc: usize,
    sp: usize,
    depth: usize,
    flags: u8,
    mode: u8,
    cycles: usize,
    running: bool,
    stdout: bool,
    output: Vec<String>,
}
impl Cpu {
    fn address(&self, a: usize, n: usize) -> VmResult<usize> {
        if a.checked_add(n).is_some_and(|end| end <= self.memory.len()) {
            Ok(a)
        } else {
            Err("TC16_MEMORY")
        }
    }
    fn byte(&mut self) -> VmResult<u8> {
        let a = self.address(self.pc, 1)?;
        let b = self.memory[a];
        self.pc += 1;
        Ok(b)
    }
    fn word(&mut self) -> VmResult<u16> {
        let lo = self.byte()?;
        Ok(u16::from_le_bytes([lo, self.byte()?]))
    }
    fn read(&self, a: usize) -> VmResult<u16> {
        self.address(a, 2)?;
        Ok(u16::from_le_bytes([self.memory[a], self.memory[a + 1]]))
    }
    fn write(&mut self, a: usize, v: u16) -> VmResult<()> {
        self.address(a, 2)?;
        self.memory[a..a + 2].copy_from_slice(&v.to_le_bytes());
        Ok(())
    }
    fn push(&mut self, v: u16) -> VmResult<()> {
        let next = self.sp.checked_sub(2).ok_or("TC16_MEMORY")?;
        self.address(next, 2)?;
        self.sp = next;
        self.write(self.sp, v)?;
        self.depth += 1;
        Ok(())
    }
    fn pop(&mut self) -> VmResult<u16> {
        if self.depth == 0 {
            return Err("TC16_STACK");
        };
        let v = self.read(self.sp)?;
        self.sp += 2;
        self.depth -= 1;
        Ok(v)
    }
    fn flags(&mut self, result: i64, carry: bool, overflow: bool, half: bool) -> u16 {
        let v = result as u16;
        self.flags = (self.flags & 48)
            | if v == 0 { 1 } else { 0 }
            | if carry { 2 } else { 0 }
            | if v & 32768 != 0 { 4 } else { 0 }
            | if overflow { 8 } else { 0 }
            | if half { 64 } else { 0 }
            | if v.count_ones() % 2 == 0 { 128 } else { 0 };
        v
    }
    fn bcd(&mut self, a: u16, b: u16, subtract: bool) -> VmResult<u16> {
        fn decimal(v: u16) -> VmResult<i64> {
            let mut n = 0;
            for i in 0..4 {
                let d = (v >> (4 * i)) & 15;
                if d > 9 {
                    return Err("TC16_BCD");
                };
                n += i64::from(d) * 10i64.pow(i);
            }
            Ok(n)
        }
        let n = if subtract {
            decimal(a)? - decimal(b)?
        } else {
            decimal(a)? + decimal(b)?
        };
        let v = n.rem_euclid(10000);
        let mut packed = 0i64;
        for i in 0..4 {
            packed |= ((v / 10i64.pow(i)) % 10) << (4 * i)
        }
        Ok(self.flags(packed, !(0..10000).contains(&n), false, false))
    }
    fn step(&mut self) -> VmResult<()> {
        let op = self.byte()? as usize;
        if op >= OPS.len() {
            return Err("INVALID_TC16");
        };
        let (mut dst, mut src, mut imm) = (0usize, 0usize, 0u16);
        if [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 15, 18, 28, 29, 35, 36].contains(&op) {
            let arg = self.byte()?;
            dst = (arg >> 4) as usize;
            src = (arg & 15) as usize;
        } else if [2, 12, 13, 14, 16, 17, 19, 20, 40, 41, 43].contains(&op) {
            dst = self.byte()? as usize;
            if dst > 15 {
                return Err("INVALID_TC16");
            };
            if op == 2 {
                imm = self.word()?
            } else if op == 16 || op == 17 {
                imm = self.byte()? as u16;
                if imm > 15 {
                    return Err("INVALID_TC16");
                }
            }
        } else if [21, 22, 23, 24, 25, 26, 30, 31, 32, 33, 42].contains(&op) {
            imm = self.word()?
        }
        let (a, b) = (self.r[dst], self.r[src]);
        match op {
            0 => self.running = false,
            1 => self.r[dst] = b,
            2 => self.r[dst] = imm,
            3 => self.r[dst] = self.read(b as usize)?,
            4 => self.write(a as usize, b)?,
            5 => self.r[dst] = u16::from(self.memory[self.address(b as usize, 1)?]),
            6 => {
                let address = self.address(a as usize, 1)?;
                self.memory[address] = b as u8;
            }
            7 | 8 | 13 | 14 | 15 => {
                let sub = [8, 14, 15].contains(&op);
                let b = if op == 13 || op == 14 { 1 } else { b };
                let r = if sub {
                    i64::from(a) - i64::from(b)
                } else {
                    i64::from(a) + i64::from(b)
                };
                let overflow = (((if sub {
                    i64::from(a ^ b)
                } else {
                    !i64::from(a ^ b)
                }) & (i64::from(a) ^ r))
                    & 32768)
                    != 0;
                let v = if self.mode == 1 && op != 15 {
                    self.bcd(a, b, sub)?
                } else {
                    self.flags(
                        r,
                        !(0..=65535).contains(&r),
                        overflow,
                        if sub {
                            (a & 15) < (b & 15)
                        } else {
                            (a & 15) + (b & 15) > 15
                        },
                    )
                };
                if op != 15 {
                    self.r[dst] = v
                }
            }
            9 | 10 | 11 | 12 => {
                let v = match op {
                    9 => a & b,
                    10 => a | b,
                    11 => a ^ b,
                    _ => !a,
                };
                self.r[dst] = self.flags(i64::from(v), false, false, false)
            }
            16 | 17 => {
                let carry = if imm == 0 {
                    self.flags & 2 != 0
                } else if op == 16 {
                    a & (1 << (16 - imm)) != 0
                } else {
                    a & (1 << (imm - 1)) != 0
                };
                let v = if op == 16 {
                    i64::from(a) << imm
                } else {
                    i64::from(a) >> imm
                };
                self.r[dst] = self.flags(v, carry, false, false)
            }
            18 => self.r.swap(dst, src),
            19 => self.push(a)?,
            20 => self.r[dst] = self.pop()?,
            21 | 22 | 23 | 24 | 25 | 26 | 42 => {
                let take = match op {
                    21 | 26 => true,
                    22 => self.flags & 1 != 0,
                    42 => self.flags & 1 == 0,
                    23 => self.flags & 2 != 0,
                    24 => self.flags & 128 != 0,
                    _ => self.flags & 8 != 0,
                };
                if take {
                    self.address(imm as usize, 1)?;
                    if op == 26 {
                        self.push(self.pc as u16)?
                    };
                    self.pc = imm as usize;
                }
            }
            27 => {
                self.pc = self.pop()? as usize;
                self.address(self.pc, 1)?;
            }
            28 | 29 => self.r[dst] = self.bcd(a, b, op == 29)?,
            30 => self.flags |= imm as u8,
            31 => self.flags &= !(imm as u8),
            32 => {
                if imm > 2 {
                    return Err("INVALID_TC16");
                };
                self.mode = imm as u8;
            }
            33 => {
                if !self.stdout || imm != 1 {
                    return Err("TC16_CAPABILITY");
                };
                self.output.push(self.r[0].to_string());
            }
            34 => {}
            35 => {
                self.r[dst] = self.flags(
                    i64::from(a) * i64::from(b),
                    u32::from(a) * u32::from(b) > 65535,
                    false,
                    false,
                )
            }
            36 => {
                if b == 0 {
                    return Err("TC16_ARITHMETIC");
                };
                self.r[dst] = self.flags(i64::from(a / b), false, false, false)
            }
            37 => {
                self.flags = self.pop()? as u8;
                self.pc = self.pop()? as usize;
                self.address(self.pc, 1)?;
            }
            38 => self.flags |= 32,
            39 => self.flags &= !32,
            40 => self.r[dst] = self.sp as u16,
            41 => {
                if a % 2 != 0 {
                    return Err("TC16_STACK");
                };
                self.sp = a as usize;
                self.depth = (65536 - self.sp) / 2;
            }
            43 => self.flags = (self.flags & !128) | if a.count_ones() % 2 == 0 { 128 } else { 0 },
            _ => return Err("INVALID_TC16"),
        };
        self.cycles += 1;
        Ok(())
    }
}
/// Execute a strictly identified package. Legacy bytes are not accepted here.
pub fn execute_package(blob: &[u8], budget: usize) -> anyhow::Result<Value> {
    anyhow::ensure!((1..=100000).contains(&budget), "instruction budget");
    anyhow::ensure!(
        blob.len() > 12 && blob.len() <= 70000 && &blob[..8] == b"TC16PKG1",
        "package header"
    );
    let size = u32::from_be_bytes(blob[8..12].try_into()?) as usize;
    anyhow::ensure!(
        (1..=4096).contains(&size) && size + 12 < blob.len(),
        "header length"
    );
    let meta: Value = serde_json::from_slice(&blob[12..12 + size])?;
    let code = &blob[12 + size..];
    anyhow::ensure!(
        meta.as_object().is_some_and(|m| m.len() == 7)
            && meta["isa_id"] == "tc16-unified-v1"
            && meta["abi_id"] == "tc16-unified-abi-v1"
            && meta["binary_format"] == "tc16-package-v1",
        "ISA/ABI mismatch"
    );
    let profile = meta["capability_profile"].as_str().unwrap_or("");
    anyhow::ensure!(
        profile == "pure-v1" || profile == "stdout-u16-v1",
        "capability profile"
    );
    anyhow::ensure!(
        code.len() <= 65536
            && meta["code_size"].as_u64() == Some(code.len() as u64)
            && meta["sha256"] == hex::encode(Sha256::digest(code)),
        "code digest"
    );
    let entry = meta["entrypoint"]
        .as_u64()
        .ok_or_else(|| anyhow::anyhow!("entry"))? as usize;
    anyhow::ensure!(entry < code.len(), "entry boundary");
    let mut cpu = Cpu {
        r: [0; 16],
        memory: vec![0; 65536],
        pc: entry,
        sp: 65536,
        depth: 0,
        flags: 0,
        mode: 0,
        cycles: 0,
        running: true,
        stdout: profile == "stdout-u16-v1",
        output: Vec::new(),
    };
    cpu.memory[..code.len()].copy_from_slice(code);
    let mut exception: Option<&str> = None;
    for _ in 0..budget {
        if let Err(error) = cpu.step() {
            exception = Some(error);
            break;
        };
        if !cpu.running {
            break;
        }
    }
    Ok(
        json!({"isa_id":"tc16-unified-v1","abi_id":"tc16-unified-abi-v1","registers":cpu.r,"pc":cpu.pc,"sp":cpu.sp,"flags":cpu.flags,"mode":cpu.mode,"cycles":cpu.cycles,"halted":!cpu.running,"budget_exhausted":cpu.running&&exception.is_none(),"exception":exception,"output":cpu.output,"memory_sha256":hex::encode(Sha256::digest(&cpu.memory))}),
    )
}
