use std::collections::HashMap;

#[derive(Debug, Default)]
pub struct Config {
    values: HashMap<String, String>,
}

impl Config {
    pub fn get(&self, key: &str) -> &str {
        self.values.get(key).unwrap().as_str()
    }
}

pub fn listen_port(cfg: &Config) -> u16 {
    cfg.get("PORT").parse::<u16>().unwrap()
}
