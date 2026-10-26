import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import ts from "typescript";
const js=ts.transpileModule(fs.readFileSync(new URL("../src/theme.ts",import.meta.url),"utf8"),{compilerOptions:{module:ts.ModuleKind.ESNext}}).outputText;
const {loadTheme,saveTheme,UI_THEMES,UI_STYLES}=await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
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

test("new installs choose journal and compact upgrades retain their layout",()=>{
 stored=null;assert.equal(loadTheme().uiStyle,'journal');
 stored=JSON.stringify({uiTheme:'cockpit',wallpaper:'aurora',fontScale:125,textSpeed:40});
 const old=loadTheme();assert.equal(old.uiStyle,'cockpit');assert.equal(old.wallpaper,'aurora');assert.equal(old.fontScale,125);assert.equal(old.textSpeed,40);
 stored=JSON.stringify({uiStyle:'unknown',uiTheme:'jade'});assert.equal(loadTheme().uiStyle,'journal');
});
test("all three complete styles persist independently of color and reading settings",()=>{
 stored=JSON.stringify({uiTheme:'amethyst',wallpaper:'dusk',fontScale:140,textSpeed:25});
 for(const style of UI_STYLES){saveTheme({...loadTheme(),uiStyle:style.id});const theme=loadTheme();assert.equal(theme.uiStyle,style.id);assert.equal(theme.uiTheme,'amethyst');assert.equal(theme.wallpaper,'dusk');assert.equal(theme.fontScale,140);assert.equal(theme.textSpeed,25);}
 assert.deepEqual(UI_STYLES.map(x=>x.id),['journal','cinema','cockpit']);
});

test("HTML display location persists without changing style, colors or wallpaper",()=>{
 stored=JSON.stringify({uiStyle:'cinema',uiTheme:'lunar',wallpaper:'aurora'});
 assert.equal(loadTheme().narrativeUiMode,'inline');
 saveTheme({...loadTheme(),narrativeUiMode:'sidebar'});const theme=loadTheme();
 assert.equal(theme.narrativeUiMode,'sidebar');assert.equal(theme.uiStyle,'cinema');assert.equal(theme.uiTheme,'lunar');assert.equal(theme.wallpaper,'aurora');
 stored=JSON.stringify({...theme,narrativeUiMode:'unknown'});assert.equal(loadTheme().narrativeUiMode,'inline');
});
