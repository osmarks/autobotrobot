#[macro_use] extern crate serenity;
extern crate dotenv;
extern crate calc;
extern crate ddg;
extern crate regex;
#[macro_use] extern crate lazy_static;
extern crate reqwest;

use serenity::client::{Client, EventHandler};
use serenity::framework::standard::{StandardFramework, help_commands};
use serenity::model::{channel::Message, id::ChannelId};
use std::env;
use std::fmt::Display;
use regex::Regex;

struct Handler;

impl EventHandler for Handler {}

pub fn main() {
    dotenv::dotenv().ok();

    // Load bot token from environment, 
    let mut client = Client::new(&env::var("DISCORD_TOKEN").expect("token unavailable"), Handler)
        .expect("Error creating client");

    client.with_framework(StandardFramework::new()
        .configure(|c| 
            c
            .prefixes(vec!["++", "$", ">"])
            .allow_whitespace(true)
            .case_insensitivity(true)
            .on_mention(true))
        .help(help_commands::with_embeds)
        .before(|_context, message, _command| { println!("> {}", message.content); true })
        .command("ping", |c| c.cmd(ping).desc("Says Pong.").known_as("test"))
        .command("search", |c| c.cmd(search).desc("Executes a search using DuckDuckGo.").known_as("ddg"))
        .command("eval", |c| c.cmd(eval).desc("Evaluates an arithmetic expression.").known_as("calc"))
        .command("exec", |c| c.cmd(exec).desc("Executes code passed in codeblock with language set via Coliru. Supported languages: python, shell."))
        .command("eval-polish", |c| c.cmd(eval_polish).desc("Evaluates a Polish-notation arithmetic expression.")));

    if let Err(why) = client.start() {
        eprintln!("An error occured: {:?}", why);
    }
}

command!(ping(_context, message) {
    message.reply("Pong!")?;
});

fn send_error(channel: &ChannelId, text: &str) -> std::result::Result<(), serenity::Error>  {
    channel.send_message(|m| {
        m
            .embed(|e| e.title("Error").description(text).colour((255, 0, 0)))
    }).map(|_| ())
}

fn send_text(channel: &ChannelId, text: &str) -> std::result::Result<(), serenity::Error> {
    channel.send_message(|m| {
        m
            .embed(|e| e.title("Result").description(text).colour((0, 255, 0)))
    }).map(|_| ())
}

fn send_result<T: Display, E: Display>(message: &Message, res: &Result<T, E>) -> std::result::Result<(), serenity::Error> {
    match res {
        Ok(x) => send_text(&message.channel_id, &x.to_string()),
        Err(e) => send_error(&message.channel_id, &e.to_string())
    }
}

// Evaluate an arithmetic expression
command!(eval(_context, message, args) {
    let expr = args.multiple::<String>()?.join(" "); // yes, this is kind of undoing the work the command parser does...
    send_result(message, &calc::eval(&expr))?;
});

// Evaluate an arithmetic expression in polish notation
command!(eval_polish(_context, message, args) {
    let expr = args.multiple::<String>()?.join(" ");
    send_result(message, &calc::eval_polish(&expr))?;
});

fn execute_coliru(command: &str, code: &str) -> Result<String, reqwest::Error> {
    lazy_static! {
        static ref CLIENT: reqwest::Client = reqwest::Client::new();
    }

    let mut data = std::collections::HashMap::new();
    data.insert("src", code);
    data.insert("cmd", command);

    let mut res = CLIENT.post("http://coliru.stacked-crooked.com/compile")
        .json(&data)
        .send()?;

    Ok(res.text()?)
}

// Thanks StackOverflow!
fn truncate(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        None => s,
        Some((idx, _)) => &s[..idx],
    }
}

fn to_code_block(s: &str) -> String {
    format!("```\n{}\n```", truncate(s, 1990)) // Discord only allows 2000 Unicode codepoints per message
}

fn execute_and_respond(channel: &ChannelId, command: &str, code: &str) -> Result<(), serenity::Error> {
    let coliru_result = execute_coliru(command, code);

    match coliru_result {
        Ok(stdout) => {
            channel.send_message(|m|
                m.content(&to_code_block(&stdout)))?;
        },
        Err(e) => send_error(channel, &format!("{}", e))?
    }

    Ok(())
}

command!(exec(_context, message) {
    lazy_static! {
        static ref RE: Regex = Regex::new("(?s)^.*exec.*```([a-zA-Z0-9_\\-+]+)\n(.+)```").unwrap();
    }

    let captures = match RE.captures(&message.content) {
        Some(x) => x,
        // Presumably just returning the Result from send_error should work, but it doesn't.
        None => {
            send_error(&message.channel_id, r#"Invalid format; expected a codeblock with a language set."#)?;
            return Ok(());
        }
    };

    let code = &captures[2];
    let lang = captures[1].to_lowercase();
    let lang = lang.as_str();
    let channel = &message.channel_id;

    match lang {
        "test" => execute_and_respond(channel, "echo Hello, World!", ""),
        "py" | "python" => execute_and_respond(channel, "mv main.cpp main.py && python main.py", code),
        "sh" | "shell" => execute_and_respond(channel, "mv main.cpp main.sh && sh main.sh", code),
        "lua" => execute_and_respond(channel, "mv main.cpp main.lua && lua main.lua", code),
        "haskell" | "hs" => execute_and_respond(channel, "mv main.cpp main.hs && runhaskell main.hs", code),
        _ => send_error(channel, &format!("Unknown language `{}`.", lang))
    }?;
});

// BELOW THIS LINE BE DRAGONS

struct SearchResult {
    url: Option<String>,
    image: Option<String>,
    text: String,
    title: String
}

fn send_search_result(channel: &ChannelId, res: SearchResult) -> std::result::Result<(), serenity::Error> {
    channel.send_message(|m| {
        m
            .embed(|e| {
                let e = e.title(res.title).description(res.text).colour((0, 255, 255));
                let e = match res.url {
                    Some(u) => e.url(u),
                    None => e
                };
                let e = match res.image {
                    Some(u) => e.image(u),
                    None => e
                };
                e
        })
    }).map(|_| ())
}

fn none_if_empty(s: String) -> Option<String> {
    if s.len() == 0 {
        None
    } else {
        Some(s)
    }
}

fn get_topics(t: ddg::RelatedTopic) -> Vec<ddg::response::TopicResult> {
    match t {
        ddg::RelatedTopic::TopicResult(t) => vec![t],
        ddg::RelatedTopic::Topic(t) => {
            let mut out = vec![];
            for subtopic in t.topics {
                out.append(&mut get_topics(subtopic))
            }
            out
        }
    }
}

command!(search(_context, message, args) {
    let query = args.multiple::<String>()?.join(" ");
    let result = ddg::Query::new(query.as_str(), "autobotrobot").no_html().execute()?;
    let channel = &message.channel_id;

    match result.response_type {
        ddg::Type::Article | ddg::Type::Name => send_search_result(channel, SearchResult {
            title: query,
            image: none_if_empty(result.image),
            text: result.abstract_text,
            url: none_if_empty(result.abstract_url)
        })?,
        ddg::Type::Disambiguation => {
            for related_topic in result.related_topics {
                for topic in get_topics(related_topic) {
                    send_search_result(channel, SearchResult {
                    url: none_if_empty(topic.first_url),
                    image: none_if_empty(topic.icon.url),
                    title: query.clone(),
                    text: topic.text
                })?;
                }
            }
        },
        ddg::Type::Exclusive => { 
            send_search_result(channel, SearchResult {
                title: query,
                text: result.redirect.clone(),
                image: None,
                url: Some(result.redirect)
            })?
        },
        ddg::Type::Nothing => send_error(channel, "No results.")?,
        other => send_error(channel, &format!("{:?} - unrecognized result type", other))?
    }
});