// Authoring-only: exact, original scientific PNGs become image-heavy lecture slides.
// Usage: node script.mjs WORKSPACE RUNTIME_NODE_MODULES SKILL_DIR RUNTIME_PYTHON
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
const [workspaceDir, modules, skillDir, pythonExecutable] = process.argv.slice(2);
process.env.RUNTIME_NODE_MODULES=modules;
const { Presentation, PresentationFile } = await import(pathToFileURL(path.join(modules, "@oai/artifact-tool/dist/artifact_tool.mjs")).href);
const { finalizePresentation } = await import(pathToFileURL(path.join(skillDir,"container_tools/artifact_tool_utils.mjs")).href);
const staging = path.join(workspaceDir,".local/benchmarks/media-build");
const assets = path.join(workspaceDir,"benchmarks/academic/v1/assets");
await fs.mkdir(staging,{recursive:true});
const presentation = Presentation.create({slideSize:{width:1280,height:720}});
for (let index=1;index<=2;index++) {
  const slide=presentation.slides.add();
  slide.background.fill="#fafafa";
  const title=slide.shapes.add({geometry:"textbox",position:{left:35,top:8,width:1200,height:38},fill:"none",line:{fill:"none",width:0}});
  title.text=`Fictional Meridian University | BIO201 | Image lecture slide ${index}`;
  title.text.style={typeface:"Arial",fontSize:20,color:"#173344"};
  const bytes=await fs.readFile(path.join(assets,`figure-${index}.png`));
  slide.images.add({blob:bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength),contentType:"image/png",alt:`Original synthetic scientific plot ${index}; inspect pixels`,fit:"contain",position:{left:0,top:46,width:1280,height:674}});
  await fs.writeFile(path.join(staging,`slide-${index}.png`),new Uint8Array(await (await presentation.export({slide,format:"png",scale:1})).arrayBuffer()));
}
const candidatePath=path.join(staging,"candidate.pptx");
await (await PresentationFile.exportPptx(presentation)).save(candidatePath);
const result=await finalizePresentation({workspaceDir,candidatePath,finalPath:path.join(assets,"scientific-lecture.pptx"),pythonExecutable,
  explicitTotalSlideCount:2,requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
  integrityValidatorPath:path.join(skillDir,"container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath:path.join(skillDir,"container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs:["--expected-slide-size-emu","12192000,6858000","--validate-heading-fit"],
  fontPolicy:{basis:"design",families:["Arial"]},verifyArtifactToolImport:true,
  receiptPath:path.join(staging,"validation.json")});
console.log(JSON.stringify(result));
