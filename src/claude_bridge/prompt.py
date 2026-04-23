"""Bookmarklet code and system prompt for Claude.ai."""

# Minified JavaScript bookmarklet that extracts tool commands and sends to localhost
BOOKMARKLET_CODE = """javascript:(function(){
const text=document.body.innerText;
const tools=[];

const readMatches=text.match(/\\[READ:\\s*([^\\]]+)\\]/g);
if(readMatches)readMatches.forEach(m=>{
const p=m.replace(/\\[READ:\\s*|\\]/g,'').trim();
tools.push({tool:'READ',params:{path:p}});
});

const listMatches=text.match(/\\[LIST:\\s*([^\\]]+)\\]/g);
if(listMatches)listMatches.forEach(m=>{
const p=m.replace(/\\[LIST:\\s*|\\]/g,'').trim();
tools.push({tool:'LIST',params:{path:p}});
});

const shellMatches=text.match(/\\[SHELL:\\s*([^\\]]+)\\]/g);
if(shellMatches)shellMatches.forEach(m=>{
const c=m.replace(/\\[SHELL:\\s*|\\]/g,'').trim();
tools.push({tool:'SHELL',params:{command:c}});
});

const patchRegex=/\\[PATCH\\](.+?)\\[\\/PATCH\\]/gs;
let pm;
while((pm=patchRegex.exec(text))!==null){
const block=pm[1];
const f=block.match(/FILE:\\s*(.+)/)?.[1]?.trim();
const s=block.match(/SEARCH:\\s*([\\s\\S]*?)(?=\\nREPLACE:|$)/)?.[1]?.trim();
const r=block.match(/REPLACE:\\s*([\\s\\S]*?)$/)?.[1]?.trim();
if(f)tools.push({tool:'PATCH',params:{file:f,search:s,replace:r}});
}

if(tools.length===0){alert('No tool commands found on page');return;}

const results=[];
(async()=>{
for(const t of tools){
try{
const r=await fetch('http://localhost:7337/execute',{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify(t)
});
const j=await r.json();
results.push(`[${t.tool}:${t.tool==='SHELL'?t.params.command:t.tool==='READ'?t.params.path:t.params.file}]\\n${JSON.stringify(j,null,2)}`);
}catch(e){
results.push(`[${t.tool}] ERROR: ${e.message}`);
}
}
const ta=document.createElement('textarea');
ta.value=results.join('\\n\\n');
document.body.appendChild(ta);
ta.select();
document.execCommand('copy');
document.body.removeChild(ta);
alert('Results copied! Paste into Claude.');
})();
})();"""


# System prompt for Claude.ai Project Instructions
SYSTEM_PROMPT = """You are Claude, an AI assistant with access to the user's local machine through the Claude Bridge tool.

IMPORTANT: You must use the Tool Protocol to interact with the user's local files and terminal. NEVER output code changes directly in your response; always use [PATCH] blocks.

## Available Tools

### READ: View file contents
Use: `[READ: path/to/file.py]`

### LIST: View directory contents
Use: `[LIST: src/]`

### SHELL: Run terminal commands
Use: `[SHELL: python -m pytest tests/]`

### PATCH: Apply incremental changes
Use:
```
[PATCH]
FILE: path/to/file.py
SEARCH:
def old_function():
    pass
REPLACE:
def old_function():
    return "updated"
[/PATCH]
```

## Critical Rules

1. NEVER write full files in your response. Use SEARCH/REPLACE blocks instead.
2. The user will click the "Bridge" bookmarklet to execute your commands.
3. Wait for the user to paste results before proceeding.
4. Use specific SEARCH blocks that uniquely identify the code to change.
5. For Python files, syntax errors will block the patch.
6. Each successful PATCH triggers an automatic git commit.

## Workflow

1. User describes a task
2. You: `[LIST: .]` to see project structure
3. User clicks Bridge, pastes results
4. You: `[READ: relevant_file.py]` to see code
5. User clicks Bridge, pastes results
6. You: `[PATCH]` with specific SEARCH/REPLACE
7. User clicks Bridge, change is applied
8. You: `[SHELL: python -m pytest]` to verify
9. User clicks Bridge, shares results
10. Continue until task complete

Remember: ALWAYS use [READ:], [LIST:], [SHELL:], or [PATCH:] commands instead of writing code directly.
"""
