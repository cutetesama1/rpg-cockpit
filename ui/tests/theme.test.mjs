import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const js=ts.transpileModule(fs.readFileSync(new URL("../src/theme.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {loadTheme,saveTheme,UI_THEMES}=await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
let stored=null;
globalThis.localStorage={getItem:()=>stored,setItem:(_key,value)=>{stored=value;}};
globalThis.window={location:{search:""}};
test("old and invalid settings migrate while preserving wallpaper and font preferences",()=>{
 stored=JSON.stringify({wallpaper:'dusk',fontScale:50,custom:'data:image/png;base64,AA',uiTheme:'unknown'});
 const theme=loadTheme();assert.equal(theme.uiTheme,'cockpit');assert.equal(theme.wallpaper,'dusk');assert.equal(theme.fontScale,50);assert.equal(theme.custom,'data:image/png;base64,AA');
});
test("all themes persist independently of wallpaper",()=>{
 for(const item of UI_THEMES){const theme={...loadTheme(),uiTheme:item.id};saveTheme(theme);assert.equal(loadTheme().uiTheme,item.id);assert.equal(loadTheme().wallpaper,'dusk');}
 assert.equal(UI_THEMES.length,5);
});
