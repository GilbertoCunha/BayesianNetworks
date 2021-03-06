from __future__ import annotations
from src.networks.nodes import StateNode, ActionNode, UtilityNode, EvidenceNode
from src.trees.nodes import TreeBeliefNode, TreeObservationNode
from src.networks.dn import DecisionNetwork
import matplotlib.pyplot as plt
from typing import Union
import pandas as pd

Node = Union[TreeBeliefNode, TreeObservationNode]

class Tree:
    def __init__(self, horizon: int, discount: float, action_space: list[int], observation_space: list[int]):
        # Initialize arguments
        self.horizon: int = horizon
        self.discount: float = discount
        self.action_space: list[int] = action_space
        self.observation_space: list[int] = observation_space
        
        # Build the tree
        self.node = self.build_tree(0, 0)
        
    def get_horizon(self):
        return self.horizon
    
    def get_discount(self):
        return self.discount
    
    def get_action_space(self):
        return self.action_space
    
    def get_observation_space(self):
        return self.observation_space
    
    def get_node(self):
        return self.node
        
    def build_tree_aux(self, action: int, depth: int):
        # Create node
        r = TreeObservationNode(action, depth)
        
        # Create children for each observation
        if depth < self.horizon:
            for observation in self.observation_space:
                r.add_children(self.build_tree(observation, depth+1))
            
        return r
        
    def build_tree(self, observation: int, depth: int):
        # Create observation node
        r = TreeBeliefNode(observation, depth)
        
        # Add children
        for action in self.action_space:
            r.add_children(self.build_tree_aux(action, depth))
                
        return r
    
    @staticmethod
    def belief_update(ddn: DecisionNetwork, b: pd.DataFrame, a: int, o: int):
        # Get id for next state
        snid = ddn.get_nodes_by_key(lambda nid, n: (isinstance(n, StateNode) and ddn.is_root(nid)))[0]
        s_nid = ddn.get_nodes_by_key(lambda nid, n: (isinstance(n, StateNode) and (not ddn.is_root(nid))))[0]
        anid = ddn.get_nodes_by_key(lambda n: isinstance(n, ActionNode))[0]
        onid = ddn.get_nodes_by_key(lambda n: isinstance(n, EvidenceNode))[0]
        ddn.node_map[anid].set_action(a)
        r = ddn.query(query=[s_nid], evidence={onid: o})
        r = r.rename(columns={s_nid: snid}, inplace=False)
        return r
    
    def q_value(self, ddn: DecisionNetwork, obs_node: TreeObservationNode, b: pd.DataFrame):
        
        """# Set reward for current belief
        rnid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, UtilityNode))[0]
        anid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, ActionNode))[0]
        ddn.node_map[anid].set_action(obs_node.get_value())
        reward_df = ddn.query(query=[rnid])
        r = (reward_df[rnid] * reward_df["Prob"]).sum()"""
        
        # Calculate observation distribution
        snid = ddn.get_nodes_by_key(lambda nid, n: (isinstance(n, StateNode) and ddn.is_root(nid)))[0]
        rnid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, UtilityNode))[0]
        onid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, EvidenceNode))[0]
        anid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, ActionNode))[0]
        ddn.node_map[anid].set_action(obs_node.get_value())
        obs_df = ddn.query(query=[onid])
        
        # Calculate imediate reward
        ddn.node_map[snid].add_pt(b)
        reward_df = ddn.query(query=[rnid])
        r = (reward_df[rnid] * reward_df["Prob"]).sum()
        belief_list = list(b["Prob"].to_numpy())
        # print(f"   Belief: {belief_list} | Action: {obs_node.get_value()} | Reward: {r}")
        
        # Iterate every children belief node
        for b_node in obs_node.get_children():
            # Calculate new belief
            b_ = self.belief_update(ddn, b, obs_node.get_value(), b_node.get_value())
            
            # Recursive call for every children action node
            # To get greedy value
            V = float("-inf") if (b_node.get_depth() <= self.horizon) else 0
            for o_node in b_node.get_children():
                q = self.q_value(ddn, o_node, b_)
                if q > V:
                    V = q
                    
            # Increment value for observation node
            r += self.discount * obs_df[obs_df[onid] == b_node.get_value()]["Prob"].iloc[0] * V
           
        # Revert belief-state to original df
        ddn.node_map[snid].add_pt(b)
        
        return r
    
    def pomdp_lookahead(self, ddn: DecisionNetwork, verbose=False):
        # Get root belief-state
        f = lambda nid, n: isinstance(n, StateNode) and ddn.is_root(nid)
        root_state = ddn.get_nodes_by_key(f)[0]
        b = ddn.get_node(root_state).get_pt()
        
        # Iterate every action and choose the best
        r = None
        value = float("-inf")
        for obs_node in self.node.get_children():
            # Get the value of the action
            q = self.q_value(ddn, obs_node, b)
            if verbose:
                print(f"   Action: {obs_node.get_value()} | Value: {q}")
            if q > value:
                value = q
                r = obs_node.get_value()
            
        return r
    
    def online_planning(self, ddn: DecisionNetwork, time: int, verbose=False):
        # Initialize action sequences
        r = []
        
        # Iterate time-steps
        for t in range(time):
            # Select optimal action
            a = self.pomdp_lookahead(ddn)
            r.append(a)
            
            # Sample observation
            onid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, EvidenceNode))[0]
            anid = ddn.get_nodes_by_key(lambda nid, n: isinstance(n, ActionNode))[0]
            ddn.node_map[anid].set_action(a)
            o = ddn.query(query=[onid], n_samples=1)
            o = o[o["Prob"] == 1][onid].iloc[0]
            
            # Update belief-state
            snid = ddn.get_nodes_by_key(lambda nid, n: (isinstance(n, StateNode) and ddn.is_root(nid)))[0]
            b = ddn.node_map[snid].get_pt()
            b_ = self.belief_update(ddn, b, a, o)
            ddn.node_map[snid].add_pt(b_)
            
            if verbose:
                print(f"-> Time: {t} | Action: {a}")
                print(f"   Observation: {o}")
                print(f"   Belief-state:")
                print(b)
            
        return r