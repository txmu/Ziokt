package com.ziokt.effort;

import java.math.BigInteger;
import java.util.Arrays;
import org.json.JSONArray;
import org.json.JSONObject;

/** Native bounded PRP prover, including independently verifiable Gerbicz transitions. */
final class GimpsProof {
    interface Progress {void tick(int iteration,BigInteger state) throws Exception;}
    static final BigInteger ONE=BigInteger.ONE,THREE=BigInteger.valueOf(3),Q=new BigInteger("4294967311");
    static String hex(BigInteger n){return "0x"+n.toString(16);}
    static String low(BigInteger n){return String.format(java.util.Locale.ROOT,"%016X",n.and(new BigInteger("FFFFFFFFFFFFFFFF",16)).longValue());}
    static BigInteger square(BigInteger x,int count,BigInteger m,Progress progress) throws Exception {
        for(int i=0;i<count;i++){x=x.multiply(x).mod(m);progress.tick(i+1,null);}return x;
    }
    static JSONArray transition(BigInteger x,BigInteger y,int count,BigInteger m,Progress progress) throws Exception {
        JSONArray steps=new JSONArray();
        while(count>32){boolean odd=count%2==1;if(odd){x=x.multiply(x).mod(m);count--;}
            BigInteger z=square(x,count/2,m,progress);
            BigInteger r=new BigInteger(Work.hash("corium-checkpoint-v1:"+x.toString(16)+":"+y.toString(16)+":"+z.toString(16)+":"+m.toString(16)+":"+count),16);
            steps.put(Work.object("Z",hex(z),"odd",odd));x=x.modPow(r,m).multiply(z).mod(m);y=z.modPow(r,m).multiply(y).mod(m);count/=2;
        }return steps;
    }
    static JSONObject compute(int p,boolean prp,JSONObject saved,Progress progress) throws Exception {
        if(p<2||p>(prp?100000:4096))throw new IllegalArgumentException("bounded exponent required");
        BigInteger m=ONE.shiftLeft(p).subtract(ONE);
        if(!prp||p==2){BigInteger s=p==2?BigInteger.ZERO:BigInteger.valueOf(4);for(int i=0;i<p-2;i++){s=s.multiply(s).subtract(BigInteger.valueOf(2)).mod(m);progress.tick(i+1,null);}return Work.object("schema","corium.gimps-proof.v2","exponent",p,"method","lucas-lehmer","residue",s.toString(),"is_prime",s.signum()==0,"iterations",p-2);}
        BigInteger s=THREE;int first=0;
        if(saved!=null){int it=saved.optInt("iteration",-1);String text=saved.optString("s","");if(it>=0&&it<p-1&&text.length()<=(p+2)/3&&text.matches("[0-9]+")){BigInteger candidate=new BigInteger(text);if(candidate.signum()>=0&&candidate.compareTo(m)<0){s=candidate;first=it;}}}
        for(int i=first;i<p-1;i++){s=s.multiply(s).mod(m);progress.tick(i+1,s);}
        BigInteger residue=s.multiply(m.multiply(BigInteger.valueOf(2)).add(ONE).divide(THREE)).mod(m);
        boolean isPrp=residue.equals(m.subtract(ONE));JSONArray proofSteps=new JSONArray();BigInteger x=THREE,y=THREE.multiply(residue).mod(m);int count=p-1;
        for(int d=0;(count>4096||d<4)&&count>1&&d<64;d++){boolean odd=count%2==1;if(odd){x=x.multiply(x).mod(m);count--;}BigInteger z=square(x,count/2,m,progress);BigInteger r=new BigInteger(Work.hash(x+":"+y+":"+z+":"+m).substring(0,16),16);proofSteps.put(Work.object("Z",hex(z),"odd",odd));x=x.modPow(r,m).multiply(z).mod(m);y=z.modPow(r,m).multiply(y).mod(m);count/=2;}
        JSONArray checkpoints=new JSONArray();String hash=Work.hash("gerbicz-init:"+p+":3:4294967311");int previousIt=0;BigInteger previousState=THREE;
        for(int it:new int[]{0,(p-1)/2,p-1}){BigInteger state=square(previousState,it-previousIt,m,progress);String sh=Work.hash(p+":"+it+":"+state.toString(16)),res64=low(state);long mq=state.mod(Q).longValue();hash=Work.hash(hash+":"+it+":"+sh+":"+res64+":"+mq);checkpoints.put(Work.object("iteration",it,"state",hex(state),"state_hash",sh,"res64",res64,"math_residue_q",mq,"hash",hash,"transition",transition(previousState,state,it-previousIt,m,progress)));previousIt=it;previousState=state;}
        int size=Math.max(1,(int)Math.sqrt(p-1)),blocks=(p-1)/size;BigInteger blockState=THREE,product=ONE;
        for(int b=0;b<blocks;b++){product=product.multiply(blockState).mod(m);blockState=square(blockState,size,m,progress);}
        if(!square(product,size,m,progress).multiply(THREE).mod(m).equals(product.multiply(blockState).mod(m)))throw new IllegalStateException("Gerbicz identity");
        JSONObject check=Work.object("block_size",size,"blocks",blocks,"product",hex(product),"end_state",hex(blockState),"transition",transition(THREE,blockState,blocks*size,m,progress));
        boolean known=Arrays.asList(3,5,7,13,17,19,31,61,89,107,127,521,607,1279,2203,2281,3217,4253,4423,9689,9941,11213,19937,21701,23209,44497,86243).contains(p);
        return Work.object("schema","corium.gimps-prp-proof.v1","exponent",p,"method","prp-fiat-shamir","base",3,"residue",residue.toString(),"res64",low(residue),"is_prp",isPrp,"prp_result",isPrp?"PRP":"COMPOSITE","is_prime",isPrp&&known,"iterations",p-1,"proof_steps",proofSteps,"gerbicz_status","OK","gerbicz_checkpoints",checkpoints,"gerbicz_check",check);
    }
}
